# RenderJS Corpus: glossary_templates (POC v3)
version: 3.0
corpus_type: glossary_templates

## TERM: gadget
field_groups:
- layout_html
- state_logic
use_cases:
- general

Definition:
- A reusable component defined by one HTML file + its JS/CSS dependencies.
- Runtime instance has .element (DOM node) and .state (state object).
- Every gadget definition should be loadable as root gadget directly in browser URL bar.

## TERM: gadget.element
field_groups:
- layout_html
- state_logic
use_cases:
- general

Definition:
- Built-in attribute providing direct access to the gadget's DOM root node.
- All DOM queries inside a gadget must use this.element.querySelector(), never document.querySelector().

## TERM: gadget.state
field_groups:
- state_logic
use_cases:
- general

Definition:
- Built-in attribute providing read access to the gadget's current state object.
- State is set via setState() at init and updated via changeState().
- Do not modify gadget.state directly; always use changeState().

## TERM: changeState mutex
field_groups:
- state_logic
use_cases:
- general

Definition:
- changeState is sequential: it serializes state transitions.
- Each call waits for the previous changeState + onStateChange to complete before executing.
- This protects onStateChange from concurrent DOM writes.

## TERM: acquisition
field_groups:
- acquisition
use_cases:
- acquisition_bridge

Definition:
- A gadget cannot obtain a reference to its parent.
- Child acquires methods from ancestors via declareAcquiredMethod.
- Parent exposes methods to descendants via allowPublicAcquisition.
- Communication upward flows exclusively through acquisition mechanism.

## TERM: scope
field_groups:
- child_gadget
use_cases:
- child_gadget_container

Definition:
- A string identifier assigned to a child gadget when created via declareGadget.
- Used to retrieve the child later via getDeclaredGadget(scope).
- Must be unique within the parent gadget.

## TERM: sandbox
field_groups:
- child_gadget
use_cases:
- child_gadget_container

Definition:
- Isolation mode for child gadgets in declareGadget options.
- "public": child is rendered in a DOM div, shares parent document.
- "iframe": child is rendered in an iframe, fully isolated.

## TEMPLATE_NOTE: slot-filling policy
field_groups:
- state_logic
- event_binding
use_cases:
- general

Policy:
- Generate code by filling declared slots in HTML/JS skeleton.
- If evidence is insufficient, emit TODO markers instead of inventing APIs.
- Never invent RenderJS methods that do not exist in the official API.

## TEMPLATE_NOTE: forbidden patterns
field_groups:
- async_flow
- layout_html
- state_logic
use_cases:
- general

Forbidden:
- ".then(" in gadget JS — breaks RSVP cancellation chain
- "id=" in gadget HTML — causes duplicate ID conflicts when gadget reused
- Global DOM selectors (document.querySelector, document.getElementById) in gadget logic
- Calling external gadget.changeState — changeState is private
- Storing state in global variables (window.X =) — use gadget.state
- DOM writes outside onStateChange — violates state-driven rendering
- Breaking promise chains (not returning RSVP.Queue from handlers)
