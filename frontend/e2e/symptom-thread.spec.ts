import { expect, type Page, test } from "@playwright/test";

const AI_WAIT = 4 * 60_000; // live Meta triage and brief take ~30–40 s each

async function signInAs(page: Page, role: "patient" | "clinician") {
  await page.goto("/login");
  await page.getByTestId(`demo-${role}`).click();
  await expect(page).not.toHaveURL(/\/login/);
}

async function signOut(page: Page) {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/);
}

test("parent describes a sick child → urgent triage → clinician reads the brief and replies → parent sees it", async ({ page }) => {
  const stamp = `E2E ${Date.now()}`;
  await signInAs(page, "patient");
  await page.getByTestId("subject-ava").click();
  await page
    .getByTestId("composer-input")
    .fill(
      `${stamp}: My 4-year-old daughter started vomiting about four hours ago, has thrown up three times, is refusing to drink any water or apple juice because her tummy hurts, and is very lethargic. Fever of 100.4°F.`,
    );
  await page.getByTestId("composer-send").click();
  await expect(page).toHaveURL(/\/patient\/threads\/[0-9a-f-]+$/);
  const threadUrl = page.url();

  // Rules set the level immediately; Meta then asks follow-up questions.
  await expect(page.getByTestId("urgency-card")).toHaveAttribute("data-level", "URGENT");
  await expect(page.getByTestId("care-team")).toContainText("Dr. Priya Raman");
  await expect(page.getByTestId("question-chips")).toBeVisible({ timeout: AI_WAIT });
  await page.getByTestId("question-urine_last_8h-yes").click();
  await expect(page.getByTestId("message").filter({ hasText: "peed" }).last()).toContainText("Yes");
  await signOut(page);

  // Clinician: the thread is in the queue; the brief is grounded and clinician-only.
  await signInAs(page, "clinician");
  await page.getByTestId("queue-row").filter({ hasText: stamp }).getByRole("link").click();
  await expect(page.getByTestId("brief")).toBeVisible({ timeout: AI_WAIT });
  await expect(page.getByTestId("brief")).toContainText("Possible causes to consider");
  await page.getByTestId("ack-button").click();
  const reply = `Dr. Raman here (${stamp}). I'll call you in five minutes.`;
  await page.getByTestId("reply-input").fill(reply);
  await page.getByTestId("reply-send").click();
  await expect(page.getByTestId("message").filter({ hasText: reply })).toBeVisible();
  await signOut(page);

  // Parent sees the reply, and never the brief.
  await signInAs(page, "patient");
  await page.goto(threadUrl);
  await expect(page.getByTestId("message").filter({ hasText: reply })).toHaveAttribute("data-author", "CLINICIAN");
  await expect(page.getByText("Possible causes")).toHaveCount(0);
  await expect(page.getByTestId("care-team")).toContainText("seen");
});

test("an emergency message shows Call 911 within a second, without waiting for the model", async ({ page }) => {
  await signInAs(page, "patient");
  await page.getByTestId("subject-me").click();
  await page.getByTestId("composer-input").fill(`E2E ${Date.now()}: I have crushing chest pain and I'm sweating.`);
  const created = page.waitForResponse((r) => r.url().endsWith("/api/patient/threads") && r.request().method() === "POST");
  await page.getByTestId("composer-send").click();
  expect((await created).status()).toBe(201);
  await expect(page.getByTestId("emergency-screen")).toBeVisible({ timeout: 1000 });
  await expect(page.getByTestId("call-911")).toHaveAttribute("href", "tel:911");
});
