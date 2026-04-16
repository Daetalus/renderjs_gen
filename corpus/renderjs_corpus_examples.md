# RenderJS Corpus: code_examples (POC v3)
version: 3.0
corpus_type: code_examples
source_policy: compact snippets inspired by official docs; not normative

## Example: minimal root gadget HTML
field_groups:
- layout_html
use_cases:
- general
component_kinds:
- page

​```html
<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <script src="./rsvp.js"></script>
    <script src="./renderjs.js"></script>
    <script src="./gadget_minimal.js"></script>
  </head>
  <body>
    <div class="root">Hello RenderJS</div>
  </body>
</html>
​```

Notes:
- rsvp.js MUST come before renderjs.js in HEAD.
- No id= attributes anywhere.
- The paired JS file is referenced in HEAD.

## Example: state-driven counter (no .then)
field_groups:
- state_logic
- event_binding
- async_flow
api_names:
- rJS(window)
- setState
- onEvent
- changeState
- onStateChange
use_cases:
- general
component_kinds:
- page
- widget

​```javascript
/*global window, rJS, RSVP */
(function (window, rJS, RSVP) {
  "use strict";
  rJS(window)
    .setState({ count: 0 })
    .onEvent("click", function () {
      return this.changeState({ count: this.state.count + 1 });
    }, false, true)
    .onStateChange(function () {
      this.element.querySelector(".count-display").textContent =
        String(this.state.count);
    });
}(window, rJS, RSVP));
​```

Notes:
- IIFE wrapping with "use strict".
- setState sets initial defaults.
- onEvent only calls changeState, never writes DOM.
- onStateChange does all DOM writes via this.element.querySelector().
- onEvent returns the changeState promise (preserves chain).

## Example: RSVP.Queue chain in submit handler
field_groups:
- async_flow
- event_binding
api_names:
- onEvent
- changeState
use_cases:
- form_submit
component_kinds:
- form

​```javascript
.onEvent("submit", function () {
  var gadget = this;
  return new RSVP.Queue()
    .push(function () {
      return gadget.changeState({ loading: true, error: "" });
    })
    .push(function () {
      /* TODO: call acquired method for actual submission */
    })
    .push(undefined, function (err) {
      return gadget.changeState({ loading: false, error: String(err) });
    });
}, false, true)
​```

Notes:
- Fourth arg true = prevent_default (important for form submit).
- Error handler in .push(undefined, errorFn) pattern.
- var gadget = this; needed because inner functions lose this context.

## Example: declareMethod with mutex
field_groups:
- async_flow
api_names:
- declareMethod
use_cases:
- concurrency_control
component_kinds:
- widget

​```javascript
.declareMethod("refresh", function () {
  var gadget = this;
  return new RSVP.Queue()
    .push(function () {
      return gadget.changeState({ refreshing: true });
    })
    .push(function () {
      /* TODO: fetch data */
    })
    .push(function () {
      return gadget.changeState({ refreshing: false });
    });
}, { mutex: "refresh_mutex" })
​```

Notes:
- Third arg to declareMethod is options object with mutex.
- Same mutex name can protect multiple methods.
- Method waits for previous call with same mutex to resolve/reject.

## Example: child gadget with scope
field_groups:
- child_gadget
api_names:
- declareGadget
- getDeclaredGadget
use_cases:
- child_gadget_container
component_kinds:
- page

​```javascript
.ready(function () {
  var gadget = this;
  return gadget.declareGadget("./gadget_child.html", {
    scope: "my_child",
    sandbox: "public",
    element: gadget.element.querySelector(".child-container")
  });
})
.declareMethod("callChild", function () {
  return this.getDeclaredGadget("my_child")
    .push(function (child) {
      return child.render({ data: "hello" });
    });
})
​```

Notes:
- declareGadget returns RSVP.Queue resolved with child reference.
- Parent calls child only via declared methods (child.render).
- Parent never calls child.changeState.

## Example: acquisition bridge
field_groups:
- acquisition
api_names:
- declareAcquiredMethod
- allowPublicAcquisition
use_cases:
- acquisition_bridge
component_kinds:
- page

Child gadget JS:
​```javascript
rJS(window)
  .declareAcquiredMethod("notifyParent", "notify")
  .onEvent("click", function () {
    return this.notifyParent("button clicked");
  }, false, true)
​```

Parent gadget JS:
​```javascript
rJS(window)
  .allowPublicAcquisition("notify", function (args) {
    return this.changeState({ message: args[0] });
  })
​```

Notes:
- Child declares acquired method with local name and acquisition name.
- Parent allows public acquisition with the same acquisition name.
- args is always an array in allowPublicAcquisition callback.
- Only JSON-compatible arguments can be passed.

## Example: complete login form gadget
field_groups:
- layout_html
- state_logic
- event_binding
- async_flow
api_names:
- rJS(window)
- setState
- onEvent
- changeState
- onStateChange
use_cases:
- form_submit
component_kinds:
- form
- page

HTML:
​```html
<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <script src="./rsvp.js"></script>
    <script src="./renderjs.js"></script>
    <script src="./gadget_login.js"></script>
  </head>
  <body>
    <form class="login-form">
      <input type="text" class="username-input" placeholder="Username">
      <input type="password" class="password-input" placeholder="Password">
      <button type="submit" class="submit-btn">Login</button>
      <span class="error-msg"></span>
      <span class="status-msg"></span>
    </form>
  </body>
</html>
​```

JS:
​```javascript
/*global window, rJS, RSVP */
(function (window, rJS, RSVP) {
  "use strict";
  rJS(window)
    .setState({
      username: "",
      password: "",
      loading: false,
      error: ""
    })
    .onEvent("submit", function () {
      var gadget = this,
        form = gadget.element.querySelector(".login-form");
      return new RSVP.Queue()
        .push(function () {
          return gadget.changeState({
            username: form.querySelector(".username-input").value,
            password: form.querySelector(".password-input").value,
            loading: true,
            error: ""
          });
        })
        .push(function () {
          /* TODO: call acquired auth method */
        })
        .push(undefined, function (err) {
          return gadget.changeState({
            loading: false,
            error: String(err)
          });
        });
    }, false, true)
    .onStateChange(function () {
      var el = this.element;
      el.querySelector(".error-msg").textContent = this.state.error;
      el.querySelector(".submit-btn").disabled = this.state.loading;
      if (this.state.loading) {
        el.querySelector(".status-msg").textContent = "Loading...";
      } else {
        el.querySelector(".status-msg").textContent = "";
      }
    });
}(window, rJS, RSVP));
​```

Notes:
- Complete working example of a login form gadget.
- No id= attributes, no .then(), no global DOM access.
- DOM reads in onEvent (reading input values) are acceptable.
- DOM writes only in onStateChange.
- Form submit uses prevent_default=true (fourth arg).
