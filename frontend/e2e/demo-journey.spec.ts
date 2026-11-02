import fs from "node:fs";
import path from "node:path";
import { expect, type Page, test } from "@playwright/test";

const REPORT = path.resolve(__dirname, "../../fixtures/reports/demo-upload-lipids-thyroid.pdf");
const AI_WAIT = 5 * 60_000; // real model inference: several reasoning calls

async function signInAs(page: Page, role: "patient" | "clinician" | "administrator") {
  await page.goto("/login");
  await page.getByTestId(`demo-${role}`).click();
  await expect(page).not.toHaveURL(/\/login/);
}

async function signOut(page: Page) {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/);
}

test("patient → AI explanation → consent → handoff → clinician review → patient sees outcome", async ({ page }) => {
  // 1–2. Patient signs in and uploads a sample report as a standalone report case.
  // (The upload page was replaced by attachments in symptom threads; the report-case API remains.)
  await signInAs(page, "patient");
  const title = `E2E lipids ${Date.now()}`;
  const uploaded = await page.request.post("/api/patient/cases/upload", {
    multipart: { title, file: { name: "lipids.pdf", mimeType: "application/pdf", buffer: fs.readFileSync(REPORT) } },
  });
  expect(uploaded.status()).toBe(201);
  await page.goto(`/patient/cases/${(await uploaded.json()).case.id}`);
  const caseUrl = page.url();

  // 3. Wait for the processing agent.
  await expect(page.getByTestId("case-status")).toHaveAttribute("data-status", "SUMMARY_READY", { timeout: AI_WAIT });

  // 5. AI explanation with provenance.
  await expect(page.getByTestId("explanation-overview")).not.toBeEmpty();
  await expect(page.getByTestId("ai-provenance")).toBeVisible();

  // 4. Extracted findings preserve exact values.
  await page.getByRole("tab", { name: /Results/ }).click();
  const table = page.getByTestId("findings-table");
  await expect(table.getByRole("row", { name: /Total Cholesterol/ })).toContainText("6.4");
  await expect(table.getByRole("row", { name: /Total Cholesterol/ })).toContainText("<5.2");
  await expect(table.getByRole("row", { name: /Vitamin B12/ })).toContainText("245");

  // 6. Grant consent.
  await page.getByRole("tab", { name: "Sharing & status" }).click();
  await page.getByTestId("share-with-clinician").click();
  await expect(page).toHaveURL(/\/share$/);
  await page.getByTestId("clinician-Dr. Priya Raman").click();
  await page.getByTestId("consent-confirm").click();
  await page.getByTestId("grant-consent").click();
  await expect(page.getByTestId("case-status")).toHaveAttribute("data-status", "CONSENT_GRANTED");

  // 7. Submit the handoff; the coordinator agent performs it through tools.
  await page.getByTestId("send-handoff").click();
  await expect(page.getByTestId("case-status")).toHaveAttribute("data-status", "HANDOFF_SENT", { timeout: AI_WAIT });
  await expect(page.getByTestId("agent-trace-handoff")).toContainText("create_clinician_handoff");
  await signOut(page);

  // 8–9. Clinician signs in and acknowledges.
  await signInAs(page, "clinician");
  await page.getByTestId("clinician-case-list").getByRole("link", { name: new RegExp(title) }).click();
  await expect(page.getByTestId("clinician-summary")).toBeVisible();
  await page.getByTestId("acknowledge").click();
  await expect(page.getByTestId("case-status")).toHaveAttribute("data-status", "ACKNOWLEDGED");

  // 10–12. Review: assess the AI summary, record a decision, complete.
  await page.getByTestId("start-review").click();
  await expect(page.getByTestId("case-status")).toHaveAttribute("data-status", "UNDER_REVIEW");
  await page.getByTestId("assess-accurate").click();
  await page.getByTestId("save-assessment").click();
  await expect(page.getByText("Saved: accurate")).toBeVisible();
  await page.getByTestId("clinical-notes").fill("Lipids above target. Repeat fasting panel in 3 months.");
  await page.getByTestId("next-step").click();
  await page.getByRole("option", { name: "Repeat the laboratory test" }).click();
  await page.getByTestId("patient-message").fill("Thanks for sharing. Please book a repeat blood test in about 3 months.");
  await page.getByTestId("complete-review").click();
  await expect(page.getByTestId("case-status")).toHaveAttribute("data-status", "REVIEW_COMPLETED");
  await signOut(page);

  // 13–14. Patient sees the outcome; clinical notes stay private.
  await signInAs(page, "patient");
  await page.goto(caseUrl);
  await expect(page.getByTestId("case-status")).toHaveAttribute("data-status", "REVIEW_COMPLETED");
  const review = page.getByTestId("review-result");
  await expect(review).toContainText("Repeat the laboratory test");
  await expect(review).toContainText("book a repeat blood test");
  await expect(page.getByText("Lipids above target")).toHaveCount(0);
});

test("a clinician cannot open a case that was not shared with them", async ({ page }) => {
  await signInAs(page, "patient");
  const created = await page.request.post("/api/patient/cases", { data: { title: `E2E unshared ${Date.now()}` } });
  expect(created.status()).toBe(201);
  const unshared = await created.json();
  await signOut(page);
  await signInAs(page, "clinician");
  const res = await page.request.get(`/api/clinician/cases/${unshared.id}`);
  expect([403, 404]).toContain(res.status());
  await page.goto(`/clinician/cases/${unshared.id}`);
  await expect(page.getByText("This case has not been shared with you")).toBeVisible();
});
