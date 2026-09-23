// nanoMuse landing page: language toggle + the live phone mock in the hero.
(function () {
  "use strict";

  // ---- language -------------------------------------------------------------------
  var html = document.documentElement;
  function setLang(lang) {
    html.lang = lang;
    try {
      localStorage.setItem("nanomuse-site-lang", lang);
    } catch (e) {
      /* private mode */
    }
    document.title = lang === "zh-CN" ? "nanoMuse — 开源的个人 AI 智能体" : "nanoMuse — an open-source personal AI agent";
  }
  var saved = null;
  try {
    saved = localStorage.getItem("nanomuse-site-lang");
  } catch (e) {
    /* ignore */
  }
  var fromUrl = /[?&]lang=(zh|en)/.exec(location.search);
  if (fromUrl) setLang(fromUrl[1] === "zh" ? "zh-CN" : "en");
  else if (saved) setLang(saved);
  else setLang(/^zh/i.test(navigator.language || "") ? "zh-CN" : "en");
  document.getElementById("lang").addEventListener("click", function () {
    setLang(html.lang === "zh-CN" ? "en" : "zh-CN");
  });

  // ---- mascot ---------------------------------------------------------------------
  var MASCOT = window.NANOMUSE_MASCOT || {};
  function panda(el, mood) {
    if (!el || el.dataset.current === mood) return;
    el.dataset.current = mood;
    var badge = el.querySelector(".badge");
    // The drawing runs past the bottom of its 200×200 box on purpose (the body sits on the
    // edge); the app clips it to a circle, so does the page.
    el.innerHTML = '<span class="clip">' + (MASCOT[mood] || MASCOT.idle || "") + "</span>";
    if (badge) el.appendChild(badge);
    else if (el.classList.contains("avatar")) {
      var b = document.createElement("span");
      b.className = "badge";
      b.textContent = "1";
      el.appendChild(b);
    }
    el.classList.toggle("waiting", mood === "waiting");
  }
  Array.prototype.forEach.call(document.querySelectorAll(".beat-panda"), function (el) {
    panda(el, el.dataset.mood);
  });

  // ---- the phone mock ---------------------------------------------------------------
  var body = document.getElementById("phone-body");
  var status = document.getElementById("phone-status");
  var avatar = document.getElementById("phone-avatar");
  if (!body || !status || !avatar) return;
  var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function add(id) {
    var tpl = document.getElementById("tpl-" + id);
    if (!tpl) return null;
    var node = tpl.content.firstElementChild.cloneNode(true);
    node.dataset.id = id;
    body.appendChild(node);
    return node;
  }
  function find(id) {
    return body.querySelector('[data-id="' + id + '"]');
  }
  function done(id) {
    var n = find(id);
    if (n) n.classList.add("done");
  }
  function state(mood, s) {
    panda(avatar, mood);
    status.dataset.state = s;
  }

  // One task, start to finish, then again. Times in ms from the start of a cycle.
  var steps = [
    [0, function () { body.innerHTML = ""; state("idle", "idle"); }],
    [700, function () { add("u1"); }],
    [1600, function () { state("working", "working"); add("chip-amap"); }],
    [3300, function () { done("chip-amap"); add("chip-phone"); }],
    [5600, function () { done("chip-phone"); state("waiting", "waiting"); add("approval"); }],
    [8600, function () { var b = body.querySelector("[data-allow]"); if (b) b.classList.add("pressed"); }],
    [9100, function () { var a = find("approval"); if (a) a.remove(); state("working", "working"); add("chip-lark"); }],
    [10600, function () { done("chip-lark"); state("happy", "done"); add("a1"); }],
    [13600, function () { state("idle", "idle"); }],
  ];
  var CYCLE = 17000;

  if (reduced) {
    // A single still frame: the approval moment, which is the point of the product.
    body.innerHTML = "";
    add("u1");
    done(add("chip-amap") && "chip-amap");
    done(add("chip-phone") && "chip-phone");
    add("approval");
    state("waiting", "waiting");
    return;
  }

  var timers = [];
  function cycle() {
    timers.forEach(clearTimeout);
    timers = steps.map(function (st) {
      return setTimeout(st[1], st[0]);
    });
    timers.push(setTimeout(cycle, CYCLE));
  }
  cycle();

  // Pause the show while the tab is hidden so it does not drift.
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) timers.forEach(clearTimeout);
    else cycle();
  });
})();
