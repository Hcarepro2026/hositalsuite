/* Drag the pin, stretch the circle. Free OpenStreetMap — no Google bill. */
(function () {
  function num(id, fallback) {
    var el = document.getElementById(id);
    var v = el && el.value ? parseFloat(el.value) : NaN;
    return isFinite(v) ? v : fallback;
  }
  function write(id, value) {
    var el = document.getElementById(id);
    if (el) el.value = value;
  }
  function boot(opts) {
    if (!window.L) return;
    var latId = opts.latId;
    var lngId = opts.lngId;
    var radId = opts.radId;
    var mapId = opts.mapId;
    var host = document.getElementById(mapId);
    if (!host) return;

    var LAGOS = [6.5244, 3.3792];
    var startLat = num(latId, LAGOS[0]);
    var startLng = num(lngId, LAGOS[1]);
    var startR = Math.max(50, Math.min(2000, num(radId, 200) || 200));

    var map = L.map(mapId, { scrollWheelZoom: true }).setView([startLat, startLng], 16);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap"
    }).addTo(map);

    var marker = L.marker([startLat, startLng], { draggable: true }).addTo(map);
    var circle = L.circle([startLat, startLng], {
      radius: startR, color: "#0e5a8a", fillColor: "#12b5a5", fillOpacity: 0.18, weight: 2
    }).addTo(map);

    function syncFields() {
      var p = marker.getLatLng();
      write(latId, p.lat.toFixed(6));
      write(lngId, p.lng.toFixed(6));
      write(radId, String(Math.round(circle.getRadius())));
      var label = document.getElementById(opts.labelId || "");
      if (label) {
        label.textContent = "Circle is " + Math.round(circle.getRadius()) + " metres. Drag the pin or the edge.";
      }
    }
    function moveBoth(ll) {
      marker.setLatLng(ll);
      circle.setLatLng(ll);
      syncFields();
    }

    marker.on("drag", function (ev) { moveBoth(ev.latlng); });
    map.on("click", function (ev) { moveBoth(ev.latlng); });

    // Stretch the circle by dragging its edge.
    var stretching = false;
    circle.on("mousedown", function (ev) {
      L.DomEvent.stop(ev);
      stretching = true;
      map.dragging.disable();
    });
    map.on("mousemove", function (ev) {
      if (!stretching) return;
      var metres = map.distance(marker.getLatLng(), ev.latlng);
      circle.setRadius(Math.max(50, Math.min(2000, metres)));
      syncFields();
    });
    map.on("mouseup mouseout", function () {
      if (!stretching) return;
      stretching = false;
      map.dragging.enable();
    });

    var rad = document.getElementById(radId);
    if (rad) {
      rad.addEventListener("input", function () {
        var n = parseInt(rad.value, 10);
        if (!isFinite(n)) return;
        circle.setRadius(Math.max(50, Math.min(2000, n)));
        syncFields();
      });
    }
    ["lat", "lng"].forEach(function (kind) {
      var el = document.getElementById(kind === "lat" ? latId : lngId);
      if (!el) return;
      el.addEventListener("change", function () {
        var la = num(latId, startLat);
        var ln = num(lngId, startLng);
        moveBoth(L.latLng(la, ln));
        map.panTo([la, ln]);
      });
    });

    if (opts.locateBtn) {
      var btn = document.getElementById(opts.locateBtn);
      if (btn && navigator.geolocation) {
        btn.addEventListener("click", function () {
          navigator.geolocation.getCurrentPosition(function (pos) {
            var ll = L.latLng(pos.coords.latitude, pos.coords.longitude);
            moveBoth(ll);
            map.setView(ll, 17);
            if (window.hmsVoice && window.hmsVoice.speak) {
              window.hmsVoice.speak("Pin dropped where you are standing. Stretch the circle, then tap save.");
            }
          }, function () {
            alert("Could not read your place. Stand in the open and try again.");
          }, { enableHighAccuracy: true, timeout: 8000 });
        });
      }
    }
    setTimeout(function () { map.invalidateSize(); }, 200);
    syncFields();
  }
  window.hmsFenceMap = { boot: boot };
})();
