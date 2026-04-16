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