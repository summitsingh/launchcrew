# LaunchCrew review desk

This design is original LaunchCrew work built during the Oct 26 to Nov 4, 2026 window. Third-party packages and patterns retain their own licenses and are not claimed as new work.

## Layout and reading order

The workspace follows the human decision: brief, agent rules, run review, individual approval, receipt. A quiet green sidebar provides persistent navigation. The main canvas uses warm white panels, fine borders, compact labels, and a serif title. The brief and approved facts sit beside each other so the user can compare input with its allowed evidence. No hero illustration, decorative gradient, animated number, or publishing control competes with the task.

At narrow widths navigation moves above the content, panels stack, and button groups wrap. No content depends on hover. Run identifiers and receipt JSON wrap within their panels. The 375, 768, 1024, and 1440 pixel checks cover agent builder, approval queue, run review, and receipt. Screenshots and overflow assertions are recorded by Playwright.

## Contrast and state

Ink #182e2a sits on #f6f7f3 and white. Secondary text uses #596761. White text on #20594b marks the primary action. Pending approval uses brown text on pale amber; approved export uses dark green on pale green. State always has a written label. Icons supplement text. Disabled buttons remain native disabled controls. Errors appear in a persistent alert region; successful actions use a status region.

## Focus and forms

Every field has an explicit visible label. Native inputs preserve keyboard interaction, selection, and validation. Focus uses a three pixel amber outline with a four pixel offset, including navigation, details, and links. Navigation exposes its current page. Approval and export are separate actions on one pack. Export is absent until approval. Builder forms keep spending at zero and individual approval fixed.

## Motion and reflow

There are no decorative animations or motion effects. The reduced-motion media query also disables transitions, animations, and smooth scrolling. Flexible grids use minmax(0, 1fr); long identifiers break instead of widening the viewport. Viewports down to 375 pixels must have no horizontal document overflow.

## Visual review notes

Design choices avoided generic hero artwork, large summary counters, and redundant queue actions. Source inspection also changed fixed-width content columns to shrinkable grids, made action groups wrap, and made long receipt content wrap. Screenshot review results and any further fixes are recorded in docs/verification.md. These are implementation observations, not user research.
