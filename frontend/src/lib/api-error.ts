import type { ApiErrorBody, ValidationErrorItem } from "@/types/api";

/**
 * A single, typed failure type for everything the API client can produce.
 *
 * The backend returns `{"detail": "..."}` for application errors and
 * `{"detail": [{type, loc, msg}, ...]}` for 422 validation failures (see
 * `backend/app/main.py`). Both shapes are normalised here so no component ever
 * has to inspect raw JSON, and no stack trace ever reaches the UI.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string | undefined;
  readonly fieldErrors: Record<string, string[]>;
  readonly rawDetail: ApiErrorBody["detail"];

  constructor(
    status: number,
    message: string,
    options: {
      code?: string;
      fieldErrors?: Record<string, string[]>;
      rawDetail?: ApiErrorBody["detail"];
    } = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = options.code;
    this.fieldErrors = options.fieldErrors ?? {};
    this.rawDetail = options.rawDetail ?? message;
  }

  /** True when the session is missing/expired and the user must sign in again. */
  get isAuthError(): boolean {
    return this.status === 401;
  }

  get isForbidden(): boolean {
    return this.status === 403;
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }

  get isConflict(): boolean {
    return this.status === 409;
  }

  get isValidationError(): boolean {
    return this.status === 422;
  }

  get isRateLimited(): boolean {
    return this.status === 429;
  }

  /** 5xx, or a network-level failure where no response was received. */
  get isServerOrNetwork(): boolean {
    return this.status === 0 || this.status >= 500;
  }
}

/** Turn FastAPI's `loc` tuple into a form field name ("body.email" -> "email"). */
function locToField(loc: string[]): string {
  const meaningful = loc.filter((part) => part !== "body" && part !== "query");
  const last = meaningful[meaningful.length - 1];
  return last ?? "form";
}

function isValidationItem(value: unknown): value is ValidationErrorItem {
  return (
    typeof value === "object" &&
    value !== null &&
    "msg" in value &&
    "loc" in value
  );
}

function collectFieldErrors(items: ValidationErrorItem[]): Record<string, string[]> {
  const fields: Record<string, string[]> = {};
  for (const item of items) {
    const field = locToField(item.loc);
    (fields[field] ??= []).push(item.msg);
  }
  return fields;
}

const STATUS_FALLBACKS: Record<number, string> = {
  400: "The request was rejected by the server.",
  401: "Your session has expired. Please sign in again.",
  403: "You do not have permission to perform this action.",
  404: "The requested resource could not be found.",
  409: "That change conflicts with existing data.",
  422: "Some of the submitted values are not valid.",
  500: "The server hit an unexpected error.",
  502: "An upstream provider is unavailable.",
  503: "The service is temporarily unavailable.",
  504: "The server took too long to respond.",
};

/** Short, human sentence for any status the backend (or a proxy) can return. */
export function statusMessage(status: number): string {
  return STATUS_FALLBACKS[status] ?? `Request failed (HTTP ${status}).`;
}

/**
 * Build an `ApiError` from a non-2xx response. Returns `null` when the body is
 * not the documented error envelope so the caller can decide what to do.
 */
export function apiErrorFromResponse(
  status: number,
  body: unknown,
): ApiError {
  if (typeof body === "object" && body !== null && "detail" in body) {
    const envelope = body as ApiErrorBody;
    const code = envelope.error_code;

    if (Array.isArray(envelope.detail)) {
      const items = envelope.detail.filter(isValidationItem);
      const fieldErrors = collectFieldErrors(items);
      const message =
        items.length > 0
          ? items.map((item) => item.msg).join(" ")
          : statusMessage(status);
      return new ApiError(status, message, {
        ...(code ? { code } : {}),
        fieldErrors,
        rawDetail: envelope.detail,
      });
    }

    if (typeof envelope.detail === "string" && envelope.detail.trim()) {
      return new ApiError(status, envelope.detail, {
        ...(code ? { code } : {}),
        rawDetail: envelope.detail,
      });
    }
  }

  return new ApiError(status, statusMessage(status));
}

/** Normalise any thrown value (network failure, abort, unknown) into ApiError. */
export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  if (error instanceof DOMException && error.name === "AbortError") {
    return new ApiError(0, "The request was cancelled.");
  }
  if (error instanceof TypeError) {
    return new ApiError(
      0,
      "Cannot reach the Digital Twin API. Check that the backend is running and that NEXT_PUBLIC_API_URL is correct.",
    );
  }
  if (error instanceof Error) {
    return new ApiError(0, error.message);
  }
  return new ApiError(0, "Unexpected error.");
}

/**
 * Presentation-safe message for any error. Keeps provider details (which the
 * backend already sanitises) but never surfaces raw objects or traces.
 */
export function errorMessage(error: unknown): string {
  const apiError = toApiError(error);
  if (apiError.status === 0) return apiError.message;
  if (apiError.isValidationError) return apiError.message;
  return apiError.message || statusMessage(apiError.status);
}