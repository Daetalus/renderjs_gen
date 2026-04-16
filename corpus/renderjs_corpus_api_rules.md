# RenderJS Corpus: rules_api (POC v3)
version: 3.0
corpus_type: rules_api
source_policy: summarized from official Nexedi documentation
note: This file is normative. Prefer it when conflicts occur with other corpus files.

## Scope
field_groups:
- layout_html
- state_logic
- event_binding
- async_flow
- acquisition
- child_gadget
- error_boundary
api_names:
- rJS(window)
- ready
- declareMethod
- declareService
- declareJob
- onEvent
- onLoop
- setState
- onStateChange
- changeState
- declareGadget
- getDeclaredGadget
- dropGadget
- allowPublicAcquisition
- declareAcquiredMethod
- getInterfaceList
- getMethodList
- getRequiredCSSList
- getRequiredJSList
- getPath
- getTitle
use_cases:
- general

Sources (official):
- https://renderjs.nexedi.com/
- https://renderjs.nexedi.com/renderjs-Concept
- https://renderjs.nexedi.com/renderjs-API.Quickguide

## Rule: gadget = single HTML + HEAD dependencies
field_groups:
- layout_html
use_cases:
- general

Normative:
- A gadget is defined by one HTML file with JS/CSS deps in HEAD.
- HTML must include rsvp.js before renderjs.js.
- Every gadget must be loadable as root gadget in browser.
- Do not hide dependencies in runtime injection.

## Rule: DOM ownership + state-driven updates
field_groups:
- state_logic
- event_binding
use_cases:
- general

Normative:
- A gadget must not modify the global document DOM.
- It must only manage its own gadget.element subtree.
- All DOM writes MUST happen in onStateChange.
- changeState is the gadget-level mutex; it is sequential.
- onStateChange receives modification_dict containing only changed keys.

Static-check:
- Forbid document.querySelector / querySelectorAll / getElementById / document.body.
- Flag DOM writes (innerHTML, textContent, appendChild, classList.add/remove/toggle) outside onStateChange.

## Rule: never use .then()
field_groups:
- async_flow
use_cases:
- general

Normative:
- Never use Promise.prototype.then().
- Use new RSVP.Queue().push() for cancellable async chains.
- .then() creates native Promise that severs RSVP cancellation chain.
- When gadget detaches from DOM, RSVP cancels pending queues; .then() chains leak.

Static-check:
- Reject ".then(" in gadget JS (after stripping strings and comments).

## Rule: always return promise chains
field_groups:
- async_flow
- event_binding
use_cases:
- general

Normative:
- Always return the result of RSVP/RenderJS calls from handlers.
- Breaking the chain causes silent failures and prevents cancellation.

Static-check:
- In onEvent/declareMethod/declareService callbacks, verify return statement exists.

## Rule: never use DOM id attribute
field_groups:
- layout_html
use_cases:
- general

Normative:
- Do not use id= inside gadget HTML.
- Gadgets can be instantiated multiple times; duplicate IDs break the page.
- Use class or data-role selectors instead.

Static-check:
- Reject 'id=' in generated gadget HTML body (exclude <meta> and <script> tags).

## Rule: never use global variables
field_groups:
- state_logic
use_cases:
- general

Normative:
- Do not store state in global variables.
- Use gadget.state + changeState for all mutable state.
- Only exception: the IIFE parameters (window, rJS, RSVP) are acceptable.

Static-check:
- Reject "window.X =" patterns.
- Flag top-level var/let/const outside the IIFE pattern.

## Rule: never call external gadget changeState
field_groups:
- acquisition
- child_gadget
use_cases:
- general

Normative:
- changeState is private for internal gadget use only.
- Expose explicit APIs via declareMethod; call those from other gadgets.
- Parent must never call child.changeState().

Static-check:
- Reject patterns like getDeclaredGadget(...).push(... .changeState(...))

## Rule: JSON compatible arguments across gadgets
field_groups:
- acquisition
use_cases:
- acquisition_bridge

Normative:
- Only pass JSON-compatible arguments across gadget boundaries.
- No functions, DOM nodes, or circular references.
- If spec requires non-JSON types, mark TODO.

## Rule: always check returned value
field_groups:
- async_flow
use_cases:
- general

Normative:
- Always check and handle the returned value of a method call.
- Silently ignoring returned promises causes resource leaks.

## API: rJS(window)
field_groups:
- state_logic
api_names:
- rJS(window)

Signature: rJS(window) -> gadget class chain
Notes: Entry point for gadget logic. Must be inside IIFE.

## API: ready(callback)
field_groups:
- async_flow
api_names:
- ready

Signature: .ready(function() { return ...; })
Notes: Called after deps loaded. Keep lightweight. Return promise chain.

## API: setState(initial_dict)
field_groups:
- state_logic
api_names:
- setState

Signature: .setState({key: value, ...})
Notes: Sets default state once at init. Does NOT trigger onStateChange.

## API: changeState(patch_dict)
field_groups:
- state_logic
api_names:
- changeState

Signature: this.changeState({key: newValue, ...}) -> RSVP.Queue
Notes: Sequential mutex. Triggers onStateChange only if values actually changed. Returns queue that resolves when onStateChange completes.

## API: onStateChange(callback)
field_groups:
- state_logic
api_names:
- onStateChange

Signature: .onStateChange(function(modification_dict) { ... })
Notes: DOM writes happen here. modification_dict contains only changed keys. this.state has the full updated state.

## API: onEvent(type, callback, use_capture, prevent_default)
field_groups:
- event_binding
api_names:
- onEvent

Signature: .onEvent("type", function(evt) { return ...; }, false, true)
Notes: Binds on gadget.element. Callback must return promise chain. Fourth arg true = preventDefault.

## API: declareMethod(name, callback, options)
field_groups:
- async_flow
- acquisition
api_names:
- declareMethod

Signature: .declareMethod("name", function(args...) { return ...; }, {mutex: "name"})
Notes: Public API for other gadgets. Optional mutex prevents concurrency.

## API: declareService(callback)
field_groups:
- async_flow
api_names:
- declareService

Signature: .declareService(function() { return ...; })
Notes: Runs when gadget.element attached to DOM. Canceled on detach.

## API: declareJob(name, callback)
field_groups:
- async_flow
api_names:
- declareJob

Signature: .declareJob("name", function() { return ...; })
Notes: Repeated calls cancel previous unfinished job.

## API: onLoop(callback, delay_ms)
field_groups:
- async_flow
api_names:
- onLoop

Signature: .onLoop(function() { return ...; }, 5000)
Notes: Like service but only runs when tab is visible.

## API: declareGadget(url, options)
field_groups:
- child_gadget
api_names:
- declareGadget

Signature: this.declareGadget("./child.html", {scope: "name", sandbox: "public", element: domNode})
Notes: Returns RSVP.Queue resolved with child gadget. sandbox can be "public" or "iframe".

## API: getDeclaredGadget(scope)
field_groups:
- child_gadget
api_names:
- getDeclaredGadget

Signature: this.getDeclaredGadget("scope") -> RSVP.Queue
Notes: Returns queue resolved with child. Throws ScopeError if unknown.

## API: dropGadget(scope)
field_groups:
- child_gadget
api_names:
- dropGadget

Signature: this.dropGadget("scope") -> RSVP.Queue
Notes: Removes child gadget by scope.

## API: allowPublicAcquisition(name, callback)
field_groups:
- acquisition
api_names:
- allowPublicAcquisition

Signature: .allowPublicAcquisition("name", function(args) { return ...; })
Notes: Exposes method to descendants. args is always an array.

## API: declareAcquiredMethod(localName, acquisitionName)
field_groups:
- acquisition
api_names:
- declareAcquiredMethod

Signature: .declareAcquiredMethod("localName", "acquisitionName")
Notes: Acquires method from ancestor chain. Throws AcquisitionError if not found.

## API: getInterfaceList()
field_groups:
- child_gadget
api_names:
- getInterfaceList

Signature: gadget.getInterfaceList() -> list
Notes: Returns gadget's declared interfaces.

## API: getMethodList()
field_groups:
- child_gadget
api_names:
- getMethodList

Signature: gadget.getMethodList() -> list
Notes: Returns gadget's declared method names.

## API: getRequiredCSSList() / getRequiredJSList()
field_groups:
- layout_html
api_names:
- getRequiredCSSList
- getRequiredJSList

Signature: gadget.getRequiredCSSList() -> list / gadget.getRequiredJSList() -> list
Notes: Returns dependency lists declared in gadget HTML HEAD.

## API: getPath()
field_groups:
- layout_html
api_names:
- getPath

Signature: gadget.getPath() -> string
Notes: Returns the URL of the gadget definition.

## API: getTitle()
field_groups:
- layout_html
api_names:
- getTitle

Signature: gadget.getTitle() -> string
Notes: Returns the gadget title.
