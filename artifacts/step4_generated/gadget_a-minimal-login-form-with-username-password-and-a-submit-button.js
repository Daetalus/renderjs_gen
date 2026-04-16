/*global window, rJS, RSVP */
(function (window, rJS, RSVP) {
  "use strict";

  rJS(window)

    .setState({"username": "", "password": "", "error_message": "", "is_submitting": false})

.onEvent("submit", function (event) {
  var gadget = this;
  return new RSVP.Queue()
    .push(function () {
      return gadget.changeState({
        is_submitting: true,
        error_message: ""
      });
    })
    .push(function () {
      /* TODO: call acquired method for actual submission using username and password from state */
    })
    .push(undefined, function (err) {
      return gadget.changeState({
        is_submitting: false,
        error_message: String(err)
      });
    });
}, false, true)

    .onStateChange(function (modification_dict) {
      var el = this.element;
      if ('username' in modification_dict) {
        el.querySelector(".username-input").value = this.state.username;
      }
      if ('password' in modification_dict) {
        el.querySelector(".password-input").value = this.state.password;
      }
      if ('error_message' in modification_dict) {
        el.querySelector(".error-msg").textContent = this.state.error_message;
      }
      if ('is_submitting' in modification_dict) {
        el.querySelector(".submit-btn").disabled = this.state.is_submitting;
      }
    });

}(window, rJS, RSVP));
