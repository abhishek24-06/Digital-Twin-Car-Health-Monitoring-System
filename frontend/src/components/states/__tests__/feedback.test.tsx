import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ErrorState } from "@/components/states/feedback";
import { ApiError } from "@/lib/api-error";

describe("ErrorState", () => {
  it("explains a 429 rate limit and keeps the backend detail", () => {
    render(<ErrorState error={new ApiError(429, "Rate limit exceeded")} />);

    expect(screen.getByText("Too many requests")).toBeInTheDocument();
    expect(
      screen.getByText(/asking for reports faster than the server allows/i),
    ).toBeInTheDocument();
    expect(screen.getByText("Rate limit exceeded")).toBeInTheDocument();
  });

  it("still shows a generic panel for unmapped statuses", () => {
    render(<ErrorState error={new ApiError(418, "teapot")} />);
    expect(screen.getByText(/teapot/)).toBeInTheDocument();
  });
});
