# RenderJS Corpus: patterns (POC v3)
version: 3.0
corpus_type: patterns
source_policy: summarized from official Nexedi pages + howto mutex

## Pattern: state-driven rendering skeleton
field_groups:
- state_logic
- event_binding
api_names:
- setState
- changeState
- onStateChange
use_cases:
- general
component_kinds:
- page
- form
- panel
- widget

Goal:
- Keep DOM writes in onStateChange; event handlers only call changeState.

Implementation:
- .setState({key: defaultValue, ...})
- .onEvent(type, function() { return this.changeState(patch); }, capture, preventDefault)
- .onStateChange(function() { /* DOM writes using this.element.querySelector */ })

Anti-patterns:
- DOM writes inside onEvent, declareService, or declareMethod.
- Reading this.state before setState is called.

## Pattern: RSVP.Queue async chain
field_groups:
- async_flow
api_names:
- onEvent
use_cases:
- general

Correct:
- return new RSVP.Queue().push(fn).push(fn)

Wrong:
- return RSVP.delay(...).then(fn)
- return promise.then(fn)
- return someAsyncFn().then(fn)

Why:
- .then() creates native Promise that breaks RSVP cancellation chain.
- RSVP.Queue supports automatic cancellation when gadget detaches.

## Pattern: form submit with prevent_default
field_groups:
- event_binding
api_names:
- onEvent
use_cases:
- form_submit
component_kinds:
- form
- page

Implementation:
- .onEvent("submit", handler, false, true)
  - Third arg (false) = useCapture
  - Fourth arg (true) = preventDefault
- Handler should changeState to "loading" first for immediate UI feedback.
- Use var gadget = this; at top of handler for inner function access.

## Pattern: declareMethod + mutex
field_groups:
- async_flow
api_names:
- declareMethod
use_cases:
- concurrency_control

Implementation:
- .declareMethod("methodName", function() { ... }, {mutex: "mutex_name"})
- Same mutex name can protect multiple methods.
- Method waits for previous call with same mutex to resolve or reject.
- Use when method triggers state changes that must not overlap.

## Pattern: child gadget creation
field_groups:
- child_gadget
api_names:
- declareGadget
- getDeclaredGadget
use_cases:
- child_gadget_container
component_kinds:
- page
- panel

Implementation:
- In ready(): this.declareGadget(url, {scope, sandbox, element})
- Later: this.getDeclaredGadget(scope).push(function(child) { return child.someMethod(); })
- Parent interacts with child only via child's declareMethod methods.
- Parent never calls child.changeState().

Declarative alternative:
- In HTML: <div data-gadget-url="./child.html" data-gadget-scope="my_child"></div>
- Gadget is loaded automatically on page load.

## Pattern: acquisition bridge
field_groups:
- acquisition
api_names:
- declareAcquiredMethod
- allowPublicAcquisition
use_cases:
- acquisition_bridge
component_kinds:
- page
- panel

Implementation:
- Child: .declareAcquiredMethod("localName", "acquisitionName")
- Parent: .allowPublicAcquisition("acquisitionName", function(args) { ... })
- args is always an array.
- Only JSON-compatible arguments cross the bridge.

Rule:
- Child cannot access parent reference.
- Acquisition walks up the gadget tree until a handler is found.
- Throws AcquisitionError if no ancestor handles it.

## Pattern: error propagation via acquisition
field_groups:
- acquisition
- error_boundary
api_names:
- allowPublicAcquisition
use_cases:
- error_handling
component_kinds:
- page

Implementation:
- Root gadget: .allowPublicAcquisition("reportServiceError", function(args) { console.error(args[0]); })
- Root gadget: .allowPublicAcquisition("reportGadgetDeclarationError", function(args) { console.error(args[0]); })
- These handle errors from child gadget services and declaration failures.

## Pattern: IIFE wrapper
field_groups:
- state_logic
use_cases:
- general
component_kinds:
- page
- form
- widget

Implementation:
- /*global window, rJS, RSVP */
- (function (window, rJS, RSVP) {
-   "use strict";
-   rJS(window)
-     .setState(...)
-     .onEvent(...)
-     .onStateChange(...);
- }(window, rJS, RSVP));

Why:
- Prevents global variable leakage.
- "use strict" enforces stricter JS parsing.
- /*global*/ comment for linting tools.
