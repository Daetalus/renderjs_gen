from __future__ import annotations

HTML_SKELETON = """<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <title>{title}</title>
    <script src="./rsvp.js"></script>
    <script src="./renderjs.js"></script>
    <script src="./gadget_{slug}.js"></script>
  </head>
  <body>
{dom_template}
  </body>
</html>
"""


JS_SKELETON = """/*global window, rJS, RSVP */
(function (window, rJS, RSVP) {{
  "use strict";

  rJS(window)

{chain_str};

}}(window, rJS, RSVP));
"""
