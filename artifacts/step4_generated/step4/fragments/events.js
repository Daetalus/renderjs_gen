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