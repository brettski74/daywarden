import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { COLLAPSED_KEY, WIDTH_KEY, clampWidth } from "./sidebar";
import { fakeService, renderPortal } from "./test/portal";

describe("the sidebar width", () => {
  it("is never narrower than 12.5rem or wider than a third of the window", () => {
    expect(clampWidth(100, 1200, 16)).toBe(200);
    expect(clampWidth(300, 1200, 16)).toBe(300);
    expect(clampWidth(500, 1200, 16)).toBe(400);
    expect(clampWidth(100, 1200, 20)).toBe(250);
  });

  it("stays at 12.5rem when a third of the window is less than that", () => {
    expect(clampWidth(400, 450, 16)).toBe(200);
    expect(clampWidth(150, 450, 16)).toBe(200);
  });
});

async function openPortal() {
  fakeService();
  renderPortal("/parent/attempts?client=younger");
  await screen.findByRole("link", { name: "spelling-week-3" });
  return screen.getByRole("complementary", { name: "Portal" });
}

function resizeWindow(width: number) {
  act(() => {
    window.innerWidth = width;
    window.dispatchEvent(new Event("resize"));
  });
}

describe("resizing the sidebar", () => {
  it("moves with the arrow keys within the limits and keeps the width it was given", async () => {
    resizeWindow(1200);
    localStorage.setItem(WIDTH_KEY, "300");
    const sidebar = await openPortal();
    const handle = within(sidebar).getByRole("separator", { name: "Resize sidebar" });
    expect(sidebar).toHaveStyle({ width: "300px" });
    handle.focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(sidebar).toHaveStyle({ width: "316px" });
    expect(localStorage.getItem(WIDTH_KEY)).toBe("316");
    await userEvent.keyboard("{End}{ArrowRight}");
    expect(sidebar).toHaveStyle({ width: "400px" });
    await userEvent.keyboard("{Home}{ArrowLeft}");
    expect(sidebar).toHaveStyle({ width: "200px" });
    expect(handle).toHaveAttribute("aria-valuemin", "200");
    expect(handle).toHaveAttribute("aria-valuemax", "400");
  });

  it("follows a drag of its right edge", async () => {
    resizeWindow(1200);
    const sidebar = await openPortal();
    const handle = within(sidebar).getByRole("separator", { name: "Resize sidebar" });
    handle.setPointerCapture = () => undefined;
    handle.releasePointerCapture = () => undefined;
    handle.hasPointerCapture = () => true;
    fireEvent.pointerDown(handle, { pointerId: 1, clientX: 240 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 333 });
    expect(sidebar).toHaveStyle({ width: "333px" });
    fireEvent.pointerUp(handle, { pointerId: 1, clientX: 900 });
    expect(sidebar).toHaveStyle({ width: "400px" });
    expect(localStorage.getItem(WIDTH_KEY)).toBe("400");
  });

  it("shrinks back inside a narrower window", async () => {
    resizeWindow(1200);
    localStorage.setItem(WIDTH_KEY, "400");
    const sidebar = await openPortal();
    expect(sidebar).toHaveStyle({ width: "400px" });
    resizeWindow(900);
    expect(sidebar).toHaveStyle({ width: "300px" });
    resizeWindow(450);
    expect(sidebar).toHaveStyle({ width: "200px" });
  });
});

describe("collapsing the sidebar", () => {
  it("leaves only the expand chevron and Sign out, and expanding brings the width back", async () => {
    resizeWindow(1200);
    localStorage.setItem(WIDTH_KEY, "320");
    const sidebar = await openPortal();
    await userEvent.click(within(sidebar).getByRole("button", { name: "Collapse sidebar" }));
    expect(localStorage.getItem(COLLAPSED_KEY)).toBe("true");
    expect(within(sidebar).getAllByRole("button").map((button) => button.getAttribute("aria-label"))).toEqual([
      "Expand sidebar",
      "Sign out",
    ]);
    expect(within(sidebar).queryByRole("img", { name: "Daywarden" })).not.toBeInTheDocument();
    expect(within(sidebar).queryByRole("navigation")).not.toBeInTheDocument();
    expect(within(sidebar).queryByText("ada")).not.toBeInTheDocument();
    expect(within(sidebar).queryByRole("separator")).not.toBeInTheDocument();
    expect(within(sidebar).getByRole("button", { name: "Expand sidebar" })).toHaveAttribute("title", "Expand sidebar");

    await userEvent.click(within(sidebar).getByRole("button", { name: "Expand sidebar" }));
    expect(sidebar).toHaveStyle({ width: "320px" });
    expect(localStorage.getItem(COLLAPSED_KEY)).toBe("false");
    expect(within(sidebar).getByRole("navigation", { name: "Portal pages" })).toBeInTheDocument();
  });

  it("stays collapsed when the portal opens again and while moving between pages", async () => {
    localStorage.setItem(COLLAPSED_KEY, "true");
    const sidebar = await openPortal();
    expect(within(sidebar).getByRole("button", { name: "Expand sidebar" })).toBeInTheDocument();
    expect(within(sidebar).getByRole("button", { name: "Sign out" })).toHaveAttribute("title", "Sign out");
    await userEvent.keyboard("{Tab}");
    expect(within(sidebar).getByRole("button", { name: "Expand sidebar" })).toHaveFocus();
    await userEvent.keyboard("{Tab}");
    expect(within(sidebar).getByRole("button", { name: "Sign out" })).toHaveFocus();
  });

  it("keeps the expanded content while a collapse animates, then leaves the strip", async () => {
    document.documentElement.style.setProperty("--expand-duration", "150ms");
    try {
      resizeWindow(1200);
      localStorage.setItem(WIDTH_KEY, "320");
      const sidebar = await openPortal();
      await userEvent.click(within(sidebar).getByRole("button", { name: "Collapse sidebar" }));
      expect(sidebar).toHaveAttribute("data-collapsed");
      expect(sidebar).toHaveAttribute("data-moving");
      expect(sidebar).not.toHaveAttribute("data-strip");
      expect(within(sidebar).getByText("ada").closest("[inert]")).not.toBeNull();
      expect(within(sidebar).queryByRole("separator")).not.toBeInTheDocument();
      await waitFor(() => expect(sidebar).toHaveAttribute("data-strip"));
      expect(sidebar).not.toHaveAttribute("data-moving");
      expect(within(sidebar).queryByText("ada")).not.toBeInTheDocument();

      await userEvent.click(within(sidebar).getByRole("button", { name: "Expand sidebar" }));
      expect(sidebar).not.toHaveAttribute("data-strip");
      expect(sidebar).toHaveAttribute("data-moving");
      expect(sidebar).toHaveStyle({ width: "320px" });
      expect(within(sidebar).getByRole("navigation", { name: "Portal pages" })).not.toHaveAttribute("inert");
      await waitFor(() => expect(sidebar).not.toHaveAttribute("data-moving"));
    } finally {
      document.documentElement.style.removeProperty("--expand-duration");
    }
  });

  it("works from the keyboard with Enter and Space", async () => {
    const sidebar = await openPortal();
    within(sidebar).getByRole("button", { name: "Collapse sidebar" }).focus();
    await userEvent.keyboard("{Enter}");
    expect(within(sidebar).getByRole("button", { name: "Expand sidebar" })).toHaveFocus();
    await userEvent.keyboard(" ");
    expect(within(sidebar).getByRole("button", { name: "Collapse sidebar" })).toBeInTheDocument();
  });
});
