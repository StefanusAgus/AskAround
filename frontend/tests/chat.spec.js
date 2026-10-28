import { expect, test } from "@playwright/test";


test("shows three relevant starter prompts and selects one", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Where should we go?" })).toBeVisible();
  const starters = page.getByLabel("Suggested questions").getByRole("button");
  await expect(starters).toHaveCount(3);

  const labels = await starters.allTextContents();
  expect(new Set(labels).size).toBe(3);
  await starters.first().click();
  await expect(page.getByLabel("Message AskAround")).toHaveValue(labels[0]);
});


test("renders a streamed answer and resets the chat", async ({ page }) => {
  let requestBody;
  await page.route("**/api/agent/chat", async (route) => {
    requestBody = route.request().postDataJSON();
    const events = [
      [
        "tool_call",
        {
          tool: "search_google_places_nearby",
          parameters: { included_types: ["cafe"], region_code: "SG" },
        },
      ],
      [
        "agent_completed",
        {
          output: {
            answer: [
              "### Top cafes near Orchard Road",
              "",
              "1. **Fixture Cafe**",
              "- Rating: 4.8/5",
              "- [View on Google Maps](https://www.google.com/maps/search/?api=1&query=Fixture+Cafe&query_place_id=fixture-cafe)",
            ].join("\n"),
          },
        },
      ],
    ]
      .map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)
      .join("");

    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: events,
    });
  });

  await page.goto("/");
  await page.getByLabel("Message AskAround").fill("Find cafes near Orchard Road");
  await page.getByLabel("Message AskAround").press("Enter");

  await expect(page.getByRole("heading", { name: "Top cafes near Orchard Road" })).toBeVisible();
  await expect(page.locator(".assistant-answer strong")).toHaveText("Fixture Cafe");
  await expect(page.getByRole("link", { name: "View on Google Maps" })).toHaveAttribute(
    "href",
    /query_place_id=fixture-cafe$/,
  );
  await expect(page.getByText("2 events")).toBeVisible();
  await page.getByText("Execution trace").click();
  await expect(page.locator(".trace-list")).toContainText("search_google_places_nearby");

  expect(requestBody.message).toBe("Find cafes near Orchard Road");
  expect(requestBody.session_id).toMatch(/^[a-z0-9]+$/i);

  await page.getByRole("button", { name: "New chat" }).click();
  await expect(page.getByRole("heading", { name: "Where should we go?" })).toBeVisible();
  await expect(page.locator(".conversation")).toHaveCount(0);
  await expect(page.getByLabel("Suggested questions").getByRole("button")).toHaveCount(3);
});
