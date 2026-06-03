---
name: compare-options
description: Compare two to five options — products, plans, places, tools, offers — on the criteria that matter to the user, in a table the user can re-weight, with a recommendation. Use when the user asks which to pick, for a comparison, or "X vs Y".
metadata:
  author: OpenMuse
  version: "1"
---

# Compare options

The result is a page, `compare/<topic>.html`, and a recommendation in chat with the reason.

## Pin down the question

- The options (2–5). If the user named one and asked for alternatives, find at most three obvious ones with `web_search`, and say that you picked them.
- The criteria: what the user said matters, plus `recall` for standing preferences (budget, brands they avoid, "must work offline", family size…). Five to seven criteria, no more. If the user gave none, propose them in the page — do not ask first.
- The user's situation in one line at the top of the page (what it is for, budget, constraints), so the recommendation has a visible basis.

## Research

- One `web_search` per option, then `web_fetch` the one or two pages that actually contain the facts (the maker's page, a review that lists specifications, a price page). Stop there; more searching rarely changes the answer.
- Every number in the table comes from a page you read, with the page's host in the cell's tooltip (`title` attribute). No source, no number: write "—" and say so.
- Prices with the date and currency; anything that varies by region or plan, say so.

## The page

- A table: options as columns, criteria as rows; a weight (1–5) next to each criterion the user can change in the page, and a score line that recomputes live. Plain JavaScript inline; no external resources; readable on a phone (scrolls sideways).
- Under the table: one paragraph per option — what it is best for and its one real drawback. Then **Recommendation**: the pick, the reason in two sentences, and what would change the pick ("if you travel a lot, take B").
- Keep it honest: if two options are close, say they are close.

## Finish

Chat reply: the pick, the reason in one sentence, the file name; offer to `remember` a preference if one came out of it (the user said "I don't care about weight" — that is a preference). Never buy, sign up or fill forms; if the user asks you to, that is a new task with its own approval.
