import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));
vi.mock("next/navigation", () => ({ usePathname: () => "/repositories" }));

import { AppNav } from "./app-nav";

describe("AppNav", () => {
  it("enlaza todas las secciones: sin ella no habia forma de llegar a Repositorios ni a Jobs", () => {
    render(<AppNav />);

    const hrefs = screen.getAllByRole("link").map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual(["/dashboard", "/repositories", "/jobs", "/settings"]);
  });

  it("marca la seccion actual", () => {
    render(<AppNav />);

    expect(screen.getByRole("link", { name: "Repositorios" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Jobs" })).not.toHaveAttribute("aria-current");
  });
});
