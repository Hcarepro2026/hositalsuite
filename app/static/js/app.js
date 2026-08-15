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

  /* ------------------------------------------------ nav dropdown */
  window.hmsToggleMenu = function (btn) {
    var dd = btn.closest(".dd");
    var wasOpen = dd.classList.contains("open");
    document.querySelectorAll(".dd.open").forEach(function (o) { o.classList.remove("open"); });
    if (!wasOpen) dd.classList.add("open");
  };
  document.addEventListener("click", function (e) {
    if (!e.target.closest(".dd")) document.querySelectorAll(".dd.open").forEach(function (o) { o.classList.remove("open"); });
  });

  /* ------------------------------------------------ voice-to-text (Web Speech API) */
  window.hmsVoice = {
    supported: !!(window.SpeechRecognition || window.webkitSpeechRecognition),

    /* ------------------------------------------------------------------
       Dictation.

       Problems this rewrite fixes (all reported from real phones):

       1. REPEATED WORDS. Chrome on Android fires the same final result again
          after a pause, and some builds replay earlier finals. We now key every
          final on its result index, so a given phrase is committed exactly once
          no matter how many times the browser re-sends it.

       2. THE MIC STOPPED ON ITS OWN. Android ends recognition after ~5s of
          silence. The old code treated that as "user finished". Now onend
          RESTARTS it automatically while the user still wants to dictate, so
          the mic keeps listening until THEY stop it.

       3. NO AUTO-STOP WHEN FULL. If the target has a maxlength we stop once it
          is reached, and there is a hard 3-minute safety cap so a forgotten
          mic cannot record forever or drain the battery.

       4. NO FEEDBACK. The button now shows a live "listening" state and the
          interim words appear as you speak.
       ------------------------------------------------------------------ */
    MAX_MS: 180000,          /* 3-minute hard cap */

    start: function (btn, targetId) {
      var target = document.getElementById(targetId);
      if (!target) return;
      if (!this.supported) {
        this._toast(btn, "Voice typing is not available in this browser. Please type instead.");
        return;
      }
      /* second tap = the USER stopping it */
      if (btn._rec) { this.stop(btn); return; }

      var Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
      var rec = new Rec();
      rec.lang = btn.getAttribute("data-lang") || "en-NG";
      rec.continuous = true;
      rec.interimResults = true;
      rec.maxAlternatives = 1;

      var self = this;
      var base = (target.value || "").replace(/\s+$/, "");
      var committed = {};        /* resultIndex -> transcript, so nothing repeats */
      var wantStop = false;
      var limit = parseInt(target.getAttribute("maxlength") || "0", 10);

      btn._rec = rec;
      btn._stopFn = function () { wantStop = true; try { rec.stop(); } catch (e) {} };
      this._setRecording(btn, true);

      function render(interim) {
        var finals = "";
        Object.keys(committed).sort(function (a, b) { return a - b; })
          .forEach(function (k) { finals += committed[k] + " "; });
        var merged = (base ? base + " " : "") + finals + (interim || "");
        merged = merged.replace(/[ \t]+/g, " ").replace(/\s+([,.!?])/g, "$1").trim();
        if (limit > 0 && merged.length >= limit) {
          merged = merged.slice(0, limit);
          self._toast(btn, "That is the maximum length — microphone stopped.");
          btn._stopFn();
        }
        target.value = merged;
        target.dispatchEvent(new Event("input", { bubbles: true }));
      }

      rec.onresult = function (e) {
        var interim = "";
        for (var i = e.resultIndex; i < e.results.length; i++) {
          var r = e.results[i];
          var txt = (r[0] && r[0].transcript ? r[0].transcript : "").trim();
          if (!txt) continue;
          if (r.isFinal) {
            /* keyed by index: re-sent finals overwrite, never append twice */
            committed[i] = txt;
          } else {
            interim += (interim ? " " : "") + txt;
          }
        }
        render(interim);
      };

      rec.onerror = function (e) {
        var err = e && e.error;
        if (err === "no-speech" || err === "aborted") return;   /* onend will restart */
        if (err === "language-not-supported" && rec.lang !== "en-NG") {
          rec.lang = "en-NG";                                   /* fall back and continue */
          return;
        }
        wantStop = true;
        self.stop(btn);
        if (err === "not-allowed" || err === "service-not-allowed") {
          self._toast(btn, "Microphone blocked. Allow microphone access in your browser settings, or type instead.");
        } else if (err === "network") {
          self._toast(btn, "Voice typing needs internet. Please type instead.");
        } else if (err === "language-not-supported") {
          self._toast(btn, "Voice typing is not available in this language on this phone.");
        }
      };

      /* THE KEY FIX: Android ends recognition on silence. Restart unless the
         USER asked to stop (or the safety cap fired). */
      rec.onend = function () {
        if (wantStop) { self._cleanup(btn); return; }
        try { rec.start(); } catch (e) { self._cleanup(btn); }
      };

      btn._timer = setTimeout(function () {
        self._toast(btn, "Microphone stopped after 3 minutes. Tap it again to continue.");
        btn._stopFn();
      }, this.MAX_MS);

      try { rec.start(); } catch (e) { this._cleanup(btn); }
    },

    stop: function (btn) {
      if (btn && btn._stopFn) btn._stopFn();
      else this._cleanup(btn);
    },

    _setRecording: function (btn, on) {
      btn.classList.toggle("recording", !!on);
      if (on) {
        if (!btn._label) btn._label = btn.innerHTML;
        btn.innerHTML = "⏹ Listening… tap to stop";
        btn.setAttribute("aria-label", "Stop dictation");
      } else {
        btn.innerHTML = btn._label || "🎤 Speak";
        btn.setAttribute("aria-label", "Start dictation");
      }
    },

    _cleanup: function (btn) {
      if (!btn) return;
      if (btn._timer) { clearTimeout(btn._timer); btn._timer = null; }
      btn._rec = null;
      btn._stopFn = null;
      this._setRecording(btn, false);
    },

    /* Small inline message — never a blocking alert() mid-dictation. */
    _toast: function (btn, msg) {
      try {
        var host = (btn && btn.parentNode) || document.body;
        var t = document.createElement("div");
        t.className = "voice-toast";
        t.textContent = msg;
        host.appendChild(t);
        setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 5000);
      } catch (e) { /* never block the user */ }
    },

    /* Louder, clearer spoken alerts (§19): full volume, best English voice,
       layered bell at higher gain. Voice remains an enhancement, never a dependency. */
    speak: function (text, urgency) {
      var P = (window.hmsAlerts && window.hmsAlerts.prefs) ||
              { voice_enabled: true, voice_min_level: "standard" };
      if (!P.voice_enabled) return;
      var LV = { standard: 0, urgent: 1, emergency: 2 };
      if ((LV[urgency] || 0) < (LV[P.voice_min_level] || 0)) return;
      if (this.inQuietHours()) return;
      try {
        if (!('speechSynthesis' in window)) return;
        window.speechSynthesis.cancel();        // clear queue → no overlapping repeats
        var u = new SpeechSynthesisUtterance(text);
        u.lang = this.alertLang || "en-NG";      // speak in the user's chosen language
        u.volume = 1.0;                          // maximum
        u.rate = urgency === "emergency" ? 1.0 : 0.92;   // slightly slower = clearer
        u.pitch = 1.0;
        var pick = function () {
          var vs = window.speechSynthesis.getVoices();
          var v = vs.filter(function (x) { return /^en/i.test(x.lang); })
                    .sort(function (a, b) { return (b.lang === "en-NG") - (a.lang === "en-NG") ||
                                                   (b.localService - a.localService); })[0];
          if (v) u.voice = v;
          window.speechSynthesis.speak(u);
        };
        if (window.speechSynthesis.getVoices().length) pick();
        else { window.speechSynthesis.onvoiceschanged = pick; }
      } catch (e) { /* fall back silently to text */ }
    },

    bell: function (urgency) {
      try {
        var Ctx = window.AudioContext || window.webkitAudioContext;
        if (!Ctx) return;
        if (!this._actx) this._actx = new Ctx();
        var ctx = this._actx;
        if (ctx.state === "suspended") ctx.resume();
        var GAIN = 0.9;   // much louder than before (was 0.25)
        var notes = urgency === "emergency" ? [[880, 0], [660, .22], [880, .44], [660, .66], [880, .88]]
                  : urgency === "urgent" ? [[740, 0], [740, .25], [740, .5]]
                  : [[660, 0], [880, .28]];
        notes.forEach(function (n) {
          // two detuned oscillators per note = fuller, clearer chime
          [0, 3].forEach(function (det) {
            var o = ctx.createOscillator(), g = ctx.createGain();
            o.type = det ? "triangle" : "sine";
            o.frequency.value = n[0] + det;
            g.gain.setValueAtTime(0.0001, ctx.currentTime + n[1]);
            g.gain.exponentialRampToValueAtTime(GAIN, ctx.currentTime + n[1] + .02);
            g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + n[1] + .24);
            o.connect(g); g.connect(ctx.destination);
            o.start(ctx.currentTime + n[1]); o.stop(ctx.currentTime + n[1] + .28);
          });
        });
      } catch (e) { /* sound is an enhancement */ }
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
      if (window.hmsVoice && window.hmsVoice.bell) { window.hmsVoice.bell(urgency); return; }
      /* unreachable fallback kept for safety */
      window.hmsVoice.bell(urgency);
    },

    speak: function (text, urgency) {
      if (window.hmsVoice && window.hmsVoice.speak) { window.hmsVoice.speak(text, urgency); return; }
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
