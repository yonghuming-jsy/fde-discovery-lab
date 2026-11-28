# FDE Discovery Lab

FDE Discovery Lab is a case-based practice workspace for turning enterprise conversations into evidence-backed AI opportunities, solution plans, ROI estimates, and delivery handoffs.

## Training flow

1. Opportunity: qualify the trigger, problem, impact, stakeholders, and decision path.
2. Discovery: map the workflow, volume, exceptions, systems, data, and constraints.
3. Solution: define the smallest verifiable use case, integration, safeguards, and acceptance criteria.
4. Business case: estimate value, operating cost, implementation cost, ROI, and payback from editable assumptions.
5. Handoff: record scope, owners, dependencies, acceptance criteria, and the next committed step.

## Demo

The public page is a static browser-side prototype. The active case and stage can be selected with query parameters:

?case=calder&stage=opportunity

Notes stay in the current browser's local storage unless the learner exports them as Markdown. The public demo does not connect to an account system or live model.

## Improvements informed by GitHub projects

- Added a response drill with a compact coaching review: strengths, the biggest adjustment, and a suggested next question. Its feedback is rule-based and clearly labeled; it does not pretend to be an AI scorecard.
- Added a structured customer-discovery sequence that keeps the learner on the customer's context, pain, impact, buying reality, and commitment before moving into solution design.
- Added a per-field evidence label for customer-confirmed facts, assumptions, and items still to verify; the review highlights unconfirmed gaps and preserves those labels in exports.
- Added conservative, baseline, and upside ROI views so one estimate is not presented as a forecast. The sensitivity range is editable and labeled as an assumption.
- Kept the public prototype free of browser-side model keys. A future live roleplay integration should use a server-side session and explicit time/spend limits.

References reviewed:

- [GoodHand-Off/ai-sales-roleplay](https://github.com/GoodHand-Off/ai-sales-roleplay) uses scenario roleplay, a structured coaching scorecard, and server-side session and spend safeguards.
- [Pouya-Mansournia/FoundryOS customer-discovery command](https://github.com/Pouya-Mansournia/FoundryOS/blob/main/commands/customer-discovery.md) emphasizes discovery evidence and delaying solution pitches until the interview has established the problem.
- [EricGrav1/sales-game](https://github.com/EricGrav1/sales-game) demonstrates lightweight response-based practice in a single HTML page.

## Publish

The repository is published with GitHub Pages at:

https://yonghuming-jsy.github.io/fde-discovery-lab/

The training workspace can be opened directly with:

https://yonghuming-jsy.github.io/fde-discovery-lab/?case=calder&stage=opportunity

## Archived prototype

An earlier Knowledge Wiki SaaS scaffold is preserved in `archive/knowledge-wiki-saas/` for reference. It is not the FDE Discovery Lab training experience served by the public page.
