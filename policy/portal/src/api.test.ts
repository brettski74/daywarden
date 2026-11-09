import { describe, expect, it } from "vitest";
import { safeNext, signInAddress } from "./api";

describe("the return address after sign-in", () => {
  it.each([
    ["/parent/attempts?client=younger", "/parent/attempts?client=younger"],
    ["/parent/attempts/42", "/parent/attempts/42"],
    ["/parent/usage?view=quota&quota=youtube", "/parent/usage?view=quota&quota=youtube"],
    ["/parent/", "/parent/"],
    [null, "/parent/"],
    ["https://example.com/", "/parent/"],
    ["//example.com/parent/", "/parent/"],
    ["/parent/api/attempts", "/parent/"],
    ["/parent/%61pi/session", "/parent/"],
    ["/parent/assets/index.js", "/parent/"],
    ["/parent/favicon.png", "/parent/"],
    ["/parent/login?next=/parent/usage", "/parent/"],
    ["/parent/../usage", "/parent/"],
    ["/parent//api", "/parent/"],
  ])("returns %s to %s", (asked, opened) => {
    expect(safeNext(asked)).toBe(opened);
  });

  it("ties a refused request to its page, or to nothing", () => {
    expect(signInAddress("/parent/attempts?client=younger")).toBe("/login?next=%2Fparent%2Fattempts%3Fclient%3Dyounger");
    expect(signInAddress("/parent/api/attempts")).toBe("/login?next=%2Fparent%2F");
    expect(signInAddress(null)).toBe("/login");
  });
});
