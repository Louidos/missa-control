import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import App from "../src/App";

test("zeigt die Version, wenn das Panel antwortet", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ status: "ok", version: "1.2.3" }), { status: 200 }),
  );
  render(<App />);
  expect(await screen.findByText(/Version 1\.2\.3/)).toBeInTheDocument();
});

test("zeigt einen Hinweis, wenn das Panel nicht antwortet", async () => {
  vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("offline"));
  render(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent("antwortet nicht");
});
