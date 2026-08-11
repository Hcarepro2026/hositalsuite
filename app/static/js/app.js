/* Hospital Admin Manager Suite — client helpers: voice-to-text, offline capture, GPS */
(function () {
  "use strict";

  /* ------------------------------------------------ connectivity banner */
  var banner = document.getElementById("offline-banner");
  var okBanner = document.getElementById("online-banner");
  function paintConn() {
    var on = navigator.onLine;
    var chip = document.getElementById("conn-chip");
    if (chip) { chip.textContent = on ? "ONLINE" : "OFFLINE"; chip.className = "conn" + (on ? "" : " off"); }
    if (banner) banner.classList.toggle("show", !on);
    if (okBanner) okBanner.classList.toggle("show", on && window.__wasOffline === true);
    if (!on) window.__wasOffline = true;
    if (on) setTimeout(function () { if (okBanner) okBanner.classList.remove("show"); }, 4000);
  }
  window.addEventListener("online", function () { paintConn(); trySyncQueue(); });
  window.addEventListener("offline", paintConn);
  paintConn();

  /* ------------------------------------------------ voice-to-text (Web Speech API) */
  window.hmsVoice = {
    supported: !!(window.SpeechRecognition || window.webkitSpeechRecognition),
    start: function (btn, targetId) {
      var target = document.getElementById(targetId);
      if (!target) return;
      if (!this.supported) {
        alert("Voice-to-text is not supported in this browser. Please type your text instead.");
        return;
      }
      if (btn._rec) { try { btn._rec.stop(); } catch (e) {} btn._rec = null; btn.classList.remove("recording"); btn.innerHTML = "🎤 Speak"; return; }
      var Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
      var rec = new Rec();
      rec.lang = btn.getAttribute("data-lang") || "en-NG";
      rec.continuous = true;
      rec.interimResults = true;
      var base = target.value;
      btn.classList.add("recording");
      btn.innerHTML = "⏹ Stop";
      rec.onresult = function (e) {
        var interim = "", final = "";
        for (var i = 0; i < e.results.length; i++) {
          var r = e.results[i];
          if (r.isFinal) final += r[0].transcript + " ";
          else interim += r[0].transcript;
        }
        target.value = (base ? base + " " : "") + (final + interim).trim();
        target.dispatchEvent(new Event("input", { bubbles: true }));
      };
      rec.onerror = function (e) {
        btn.classList.remove("recording"); btn.innerHTML = "🎤 Speak"; btn._rec = null;
        if (e.error === "not-allowed") alert("Microphone permission denied. Please allow microphone access or type instead.");
      };
      rec.onend = function () { btn.classList.remove("recording"); btn.innerHTML = "🎤 Speak"; btn._rec = null; };
      btn._rec = rec;
      try { rec.start(); } catch (e) { btn.classList.remove("recording"); btn.innerHTML = "🎤 Speak"; }
    }
  };

  /* ------------------------------------------------ inspection: dynamic sections/units */
  window.hmsDeptCascade = function (deptSelect, sectionSelect, unitSelect, csrf) {
    if (!deptSelect) return;
    deptSelect.addEventListener("change", function () {
      sectionSelect.innerHTML = '<option value="">— Whole department —</option>';
      unitSelect.innerHTML = '<option value="">—</option>';
      unitSelect.disabled = true;
      var id = deptSelect.value;
      if (!id) { sectionSelect.disabled = true; return; }
      fetch("/inspections/departments/" + id + "/children", {
        method: "POST", headers: { "X-CSRF-Token": csrf }
      }).then(function (r) { return r.json(); }).then(function (data) {
        sectionSelect.disabled = false;
        (data.sections || []).forEach(function (s) {
          var o = document.createElement("option"); o.value = s.id; o.textContent = s.name;
          o.setAttribute("data-units", JSON.stringify(s.units || []));
          sectionSelect.appendChild(o);
        });
      }).catch(function () {});
    });
    if (sectionSelect) sectionSelect.addEventListener("change", function () {
      unitSelect.innerHTML = '<option value="">— Whole section —</option>';
      var opt = sectionSelect.options[sectionSelect.selectedIndex];
      var units = opt ? JSON.parse(opt.getAttribute("data-units") || "[]") : [];
      units.forEach(function (u) {
        var o = document.createElement("option"); o.value = u.id; o.textContent = u.name;
        unitSelect.appendChild(o);
      });
      unitSelect.disabled = units.length === 0;
    });
  };

  /* ------------------------------------------------ inspection GPS */
  window.hmsGps = function (mode, latInput, lngInput, statusEl) {
    if (mode === "disabled" || !latInput) return;
    if (!navigator.geolocation) { if (statusEl) statusEl.textContent = "GPS not available on this device."; return; }
    if (statusEl) statusEl.textContent = "Getting GPS location…";
    navigator.geolocation.getCurrentPosition(function (pos) {
      latInput.value = pos.coords.latitude.toFixed(6);
      lngInput.value = pos.coords.longitude.toFixed(6);
      if (statusEl) statusEl.textContent = "✅ GPS location captured.";
    }, function (err) {
      if (statusEl) statusEl.textContent = mode === "mandatory"
        ? "❌ GPS unavailable — submission requires location." : "GPS not captured (optional).";
    }, { enableHighAccuracy: false, timeout: 15000, maximumAge: 120000 });
  };

  /* ------------------------------------------------ score -> explanation enforcement */
  window.hmsScoreEnforce = function (form) {
    if (!form) return;
    form.querySelectorAll("input[name^='score_']").forEach(function (input) {
      input.addEventListener("change", function () {
        var no = input.name.split("_")[1];
        var box = document.getElementById("expl-box-" + no);
        if (!box) return;
        var low = parseInt(input.value, 10) <= 2;
        box.style.display = low ? "block" : "none";
        var card = box.closest(".crit-card");
        if (card) card.classList.toggle("flagged", low);
      });
    });
    form.addEventListener("submit", function (e) {
      var missing = [];
      [1, 2, 3, 4, 5].forEach(function (no) {
        var sel = form.querySelector("input[name='score_" + no + "']:checked");
        var expl = document.getElementById("explanation_" + no);
        if (sel && parseInt(sel.value, 10) <= 2 && expl && !expl.value.trim()) {
          missing.push(no);
        }
      });
      if (missing.length) {
        e.preventDefault();
        alert("Explanation required for criterion " + missing.join(", ") +
              " (score 1 or 2). Use text or the 🎤 voice button.");
        var box = document.getElementById("expl-box-" + missing[0]);
        if (box) box.scrollIntoView({ behavior: "smooth", block: "center" });
        return false;
      }
      /* stash a copy locally until the server confirms (offline safety) */
      try {
        var data = {};
        new FormData(form).forEach(function (v, k) { if (typeof v === "string") data[k] = v; });
        localStorage.setItem("hms-last-inspection", JSON.stringify({ at: Date.now(), data: data }));
      } catch (err) {}
    });
  };

  /* ------------------------------------------------ offline submission queue */
  function trySyncQueue() {
    var raw = null;
    try { raw = localStorage.getItem("hms-sync-queue"); } catch (e) {}
    if (!raw) return;
    var queue = JSON.parse(raw || "[]");
    if (!queue.length) return;
    var item = queue[0];
    fetch(item.url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": item.csrf },
      body: JSON.stringify(item.data)
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        queue.shift();
        localStorage.setItem("hms-sync-queue", JSON.stringify(queue));
        if (res.j && res.j.ok) {
          alert("Inspection " + res.j.ref + " synced successfully.");
          if (res.j.detail_url) window.location = res.j.detail_url;
        } else if (res.j && res.j.error === "duplicate") {
          alert("This inspection was already submitted (" + res.j.ref + ").");
        } else {
          alert("Sync failed: " + ((res.j && res.j.error) || "please retry"));
        }
      }).catch(function () { /* still offline */ });
  }
  window.hmsQueueSubmit = function (url, data, csrf) {
    var q = [];
    try { q = JSON.parse(localStorage.getItem("hms-sync-queue") || "[]"); } catch (e) {}
    q.push({ url: url, data: data, csrf: csrf });
    localStorage.setItem("hms-sync-queue", JSON.stringify(q));
    alert("You are offline. Your inspection has been SAVED LOCALLY and will sync automatically when connectivity returns.");
  };

  /* ------------------------------------------------ live alert engine (§19): bell + voice + browser notifications */
  window.hmsAlerts = {
    lastId: parseInt(localStorage.getItem("hms-alert-last") || "0", 10),
    prefs: { voice_enabled: true, voice_min_level: "standard", quiet_start: "22:00",
             quiet_end: "07:00", push_enabled: false },
    LEVELS: { standard: 0, urgent: 1, emergency: 2 },

    inQuietHours: function () {
      try {
        var now = new Date();
        var cur = now.getHours() * 60 + now.getMinutes();
        var p = function (s) { var x = (s || "0:0").split(":"); return parseInt(x[0], 10) * 60 + parseInt(x[1] || 0, 10); };
        var a = p(this.prefs.quiet_start), b = p(this.prefs.quiet_end);
        return a <= b ? (cur >= a && cur < b) : (cur >= a || cur < b);
      } catch (e) { return false; }
    },

    bell: function (urgency) {
      try {
        var Ctx = window.AudioContext || window.webkitAudioContext;
        if (!Ctx) return;
        var ctx = new Ctx();
        var notes = urgency === "emergency" ? [[880, 0], [660, .18], [880, .36], [660, .54]]
                  : urgency === "urgent" ? [[740, 0], [740, .2], [740, .4]]
                  : [[660, 0], [880, .22]];
        notes.forEach(function (n) {
          var o = ctx.createOscillator(), g = ctx.createGain();
          o.type = "sine"; o.frequency.value = n[0];
          g.gain.setValueAtTime(0.0001, ctx.currentTime + n[1]);
          g.gain.exponentialRampToValueAtTime(0.25, ctx.currentTime + n[1] + .02);
          g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + n[1] + .18);
          o.connect(g); g.connect(ctx.destination);
          o.start(ctx.currentTime + n[1]); o.stop(ctx.currentTime + n[1] + .2);
        });
      } catch (e) { /* sound is an enhancement */ }
    },

    speak: function (text, urgency) {
      if (!this.prefs.voice_enabled) return;
      if ((this.LEVELS[urgency] || 0) < (this.LEVELS[this.prefs.voice_min_level] || 0)) return;
      if (this.inQuietHours()) return;
      try {
        if (!('speechSynthesis' in window)) return;
        var u = new SpeechSynthesisUtterance(text);
        u.rate = urgency === "emergency" ? 1.05 : 0.98;
        u.lang = "en-NG";
        window.speechSynthesis.speak(u);
      } catch (e) { /* fall back silently to text */ }
    },

    toast: function (a) {
      var zone = document.getElementById("toast-zone");
      if (!zone) return;
      var el = document.createElement("div");
      el.className = "toast " + a.urgency;
      el.innerHTML = "<div class='t-title'>" + a.subject + "</div><div class='t-body'>" + a.body + "</div>";
      zone.appendChild(el);
      setTimeout(function () { el.style.opacity = "0"; el.style.transition = "opacity .6s";
        setTimeout(function () { el.remove(); }, 650); }, 9000);
    },

    notify: function (a) {
      if (!this.prefs.push_enabled) return;
      if (!('Notification' in window) || Notification.permission !== "granted") return;
      try { new Notification(a.subject, { body: a.body, tag: "hms-" + a.id }); } catch (e) {}
    },

    poll: function () {
      var self = this;
      fetch("/api/v1/alerts/poll?after=" + self.lastId).then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.prefs) self.prefs = data.prefs;
          (data.alerts || []).forEach(function (a) {
            self.toast(a);
            self.notify(a);
            if (!self.inQuietHours()) self.bell(a.urgency);
            self.speak(a.urgency === "emergency" ? "Attention. " + a.body
                     : a.urgency === "urgent" ? "Alert. " + a.body : a.body, a.urgency);
          });
          if (data.last_id && data.last_id > self.lastId) {
            self.lastId = data.last_id;
            localStorage.setItem("hms-alert-last", String(self.lastId));
          }
        }).catch(function () { /* offline — next pass */ });
    },

    start: function () {
      var self = this;
      self.poll();
      setInterval(function () { self.poll(); }, 30000);
    }
  };

  /* ------------------------------------------------ draft autosave for inspection form */
  window.hmsDraft = function (form, key) {
    if (!form) return;
    var saved = null;
    try { saved = JSON.parse(localStorage.getItem(key) || "null"); } catch (e) {}
    if (saved && saved.at && Date.now() - saved.at < 86400000) {
      Object.keys(saved.data || {}).forEach(function (k) {
        var el = form.elements[k];
        if (!el) return;
        if (el.type === "radio") {
          if (el.value === saved.data[k]) el.checked = true;
        } else if (el.tagName !== "SELECT" || saved.data[k]) { el.value = saved.data[k]; }
      });
      var n = document.getElementById("draft-note");
      if (n) n.style.display = "block";
    }
    var t = null;
    form.addEventListener("input", function () {
      clearTimeout(t);
      t = setTimeout(function () {
        var data = {};
        new FormData(form).forEach(function (v, k) { if (typeof v === "string") data[k] = v; });
        try { localStorage.setItem(key, JSON.stringify({ at: Date.now(), data: data })); } catch (e) {}
      }, 400);
    });
  };
})();
