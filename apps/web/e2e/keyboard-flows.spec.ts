import { expect, test } from "playwright/test";
import { expectNoCriticalAxeViolations, installAuthenticatedSession, tabTo } from "./helpers";

test("@keyboard auth and voice consent/upload flow works without a pointer", async ({ page }) => {
  await page.goto("/auth/sign-in?returnTo=/voices/new");
  const email = page.getByLabel("Email address");
  const password = page.getByLabel("Password");
  const signIn = page.getByRole("button", { name: "Sign in", exact: true });
  const demo = page.getByRole("button", { name: "Continue with local demo" });

  await tabTo(page, email);
  await page.keyboard.type("teacher@classvoice.local");
  await tabTo(page, password);
  await page.keyboard.type("incorrect-password");
  await tabTo(page, signIn);
  await page.keyboard.press("Enter");
  await expect(page.locator(".form-error[role='alert']")).toContainText("Email or password is incorrect");
  await tabTo(page, demo);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/voices\/new$/);

  const consentTrigger = page.getByRole("button", { name: "View consent statement" });
  await tabTo(page, consentTrigger);
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Permission to create a voice profile" });
  await expect(dialog).toBeVisible();
  await expect(page.getByRole("button", { name: "Close consent statement" })).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(page.getByRole("button", { name: "I understand & acknowledge" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("button", { name: "Review statement" })).toBeFocused();

  const nameInput = page.getByLabel("Voice name");
  await tabTo(page, nameInput);
  await page.keyboard.type("Synthetic teacher fixture");
  const dropzone = page.getByRole("button", { name: "Choose an audio reference sample" });
  await tabTo(page, dropzone);
  const fileChooserPromise = page.waitForEvent("filechooser");
  await page.keyboard.press("Enter");
  const fileChooser = await fileChooserPromise;
  await fileChooser.setFiles({ name: "sample.wav", mimeType: "audio/wav", buffer: Buffer.from("RIFFsynthetic-test-fixture") });
  await expect(dropzone).toContainText("sample.wav");
  const upload = page.getByRole("button", { name: /Start secure upload/ });
  await tabTo(page, upload);
  await page.keyboard.press("Enter");
  await expect(page.locator(".form-error[role='alert']")).toContainText("No audio file was sent or stored");
  await expectNoCriticalAxeViolations(page);
});

test("@keyboard Studio skip link, editor, and destructive dialog are keyboard operable", async ({ page }) => {
  await installAuthenticatedSession(page);
  await page.goto("/studio");

  const skipLink = page.getByRole("link", { name: "Skip to main content" });
  await tabTo(page, skipLink, 3);
  await expect(skipLink).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main-content")).toBeFocused();

  const lessonText = page.getByLabel("Lesson text");
  await tabTo(page, lessonText);
  await page.keyboard.type("A short keyboard-authored academic lesson.");
  const clear = page.getByRole("button", { name: "Clear" });
  await tabTo(page, clear);
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Clear this lesson text?" });
  await expect(dialog).toBeVisible();
  await expect(page.getByRole("button", { name: "Stay in Studio" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeVisible();
  await expectNoCriticalAxeViolations(page);
  const discard = dialog.getByRole("button", { name: "Discard" });
  await tabTo(page, discard);
  await page.keyboard.press("Enter");
  await expect(lessonText).toHaveValue("");
});

test("@keyboard generated audio player supports play, seek, speed, and download by keyboard", async ({ page }) => {
  await installAuthenticatedSession(page);
  await page.goto("/generations/synthetic-succeeded");
  await expect(page.getByRole("heading", { name: "Signed playback", exact: true })).toBeVisible();

  const play = page.getByRole("button", { name: "Play generated audio" });
  await tabTo(page, play);
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "Pause generated audio" })).toBeVisible();

  const seek = page.getByLabel("Seek generated audio");
  await tabTo(page, seek);
  await expect(seek).toBeEnabled();
  await page.keyboard.press("ArrowRight");
  const speed = page.getByLabel("Playback speed");
  await tabTo(page, speed);
  await page.keyboard.press("ArrowDown");
  await expect(speed).toHaveValue("1.25");

  const download = page.getByRole("link", { name: "Download audio" });
  await tabTo(page, download);
  const downloadPromise = page.waitForEvent("download");
  await page.keyboard.press("Enter");
  const downloadedFile = await downloadPromise;
  expect(downloadedFile.suggestedFilename()).toContain("classvoice-synthetic-succeeded.wav");
  await expectNoCriticalAxeViolations(page);
});

test("@keyboard account deletion requires every confirmation and preserves destructive-dialog focus", async ({ page }) => {
  await installAuthenticatedSession(page);
  await page.goto("/settings/profile");
  const deleteTrigger = page.getByRole("button", { name: "Delete account" }).first();
  await tabTo(page, deleteTrigger);
  await page.keyboard.press("Enter");

  const dialog = page.getByRole("dialog", { name: "Delete account?" });
  await expect(dialog).toBeVisible();
  await expect(page.getByRole("button", { name: "Close delete account dialog" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeVisible();
  await expectNoCriticalAxeViolations(page);

  const password = page.getByLabel("Re-enter password");
  await tabTo(page, password);
  await page.keyboard.type("twelve-characters");
  const phrase = page.getByLabel("Type DELETE MY ACCOUNT");
  await tabTo(page, phrase);
  await page.keyboard.type("DELETE MY ACCOUNT");
  const acknowledgement = page.getByRole("checkbox", { name: /I understand the complete cascade/ });
  await tabTo(page, acknowledgement);
  await page.keyboard.press("Space");
  const confirmDelete = dialog.getByRole("button", { name: "Delete account", exact: true });
  await tabTo(page, confirmDelete);
  await expect(confirmDelete).toBeEnabled();
  await page.keyboard.press("Enter");
  await expect(dialog).toBeHidden();
  await expect(deleteTrigger).toBeFocused();
  await expect(page.getByRole("status")).toContainText("no account mutation was sent");
});
