import { describe, expect, it } from "vitest";
import {
  ApiError,
  apiErrorFromResponse,
  errorMessage,
  statusMessage,
  toApiError,
} from "@/lib/api-error";

describe("apiErrorFromResponse", () => {
  it("uses the backend's string detail verbatim", () => {
    const error = apiErrorFromResponse(409, { detail: "VIN already exists" });
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(409);
    expect(error.message).toBe("VIN already exists");
    expect(error.isConflict).toBe(true);
  });

  it("maps FastAPI 422 items to per-field messages", () => {
    const error = apiErrorFromResponse(422, {
      detail: [
        { type: "string_too_short", loc: ["body", "password"], msg: "String should have at least 8 characters" },
        { type: "string_too_short", loc: ["body", "password"], msg: "Too weak" },
        { type: "missing", loc: ["body", "email"], msg: "Field required" },
      ],
    });

    expect(error.isValidationError).toBe(true);
    expect(error.fieldErrors.password).toEqual([
      "String should have at least 8 characters",
      "Too weak",
    ]);
    expect(error.fieldErrors.email).toEqual(["Field required"]);
    // "body" must not leak into the field name.
    expect(Object.keys(error.fieldErrors)).not.toContain("body");
    expect(error.message).toContain("String should have at least 8 characters");
  });

  it("keeps the sanitised error_code when the backend supplies one", () => {
    const error = apiErrorFromResponse(502, {
      detail: "The AI provider is not configured.",
      error_code: "provider_unavailable",
    });
    expect(error.code).toBe("provider_unavailable");
    expect(error.isServerOrNetwork).toBe(true);
  });

  it("falls back to a readable sentence for undocumented bodies", () => {
    const error = apiErrorFromResponse(418, "<html>teapot</html>");
    expect(error.message).toBe(statusMessage(418));
    expect(error.message).toContain("418");
  });
});

describe("toApiError", () => {
  it("treats a failed fetch as an unreachable-API condition", () => {
    const error = toApiError(new TypeError("Failed to fetch"));
    expect(error.status).toBe(0);
    expect(error.isServerOrNetwork).toBe(true);
    expect(error.message).toMatch(/NEXT_PUBLIC_API_URL|backend is running/i);
  });

  it("passes an existing ApiError through unchanged", () => {
    const original = new ApiError(403, "nope");
    expect(toApiError(original)).toBe(original);
    expect(toApiError(original).isForbidden).toBe(true);
  });

  it("normalises an abort into a cancelled request", () => {
    const abort = new DOMException("aborted", "AbortError");
    expect(toApiError(abort).message).toBe("The request was cancelled.");
  });

  it("never leaks a raw object into the message", () => {
    const error = toApiError({ unexpected: true });
    expect(error.message).toBe("Unexpected error.");
    expect(errorMessage({ unexpected: true })).toBe("Unexpected error.");
  });
});

describe("statusMessage", () => {
  it.each([
    [401, /session has expired/i],
    [403, /permission/i],
    [404, /could not be found/i],
    [409, /conflicts/i],
    [422, /not valid/i],
    [503, /temporarily unavailable/i],
  ])("describes %i", (status, pattern) => {
    expect(statusMessage(status)).toMatch(pattern);
  });
});
