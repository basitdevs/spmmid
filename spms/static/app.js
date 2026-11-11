// Confirmation prompts and the earned value S-curve.
document.addEventListener("submit", function (event) {
  var message = event.target.getAttribute("data-confirm");
  if (message && !window.confirm(message)) event.preventDefault();
});

function drawCurve(id, data) {
  var host = document.getElementById(id);
  if (!host || !data.length) return;
  var W = Math.max(host.clientWidth, 480), H = 280, L = 62, R = 44, T = 12, B = 30;
  var series = [["pv", "PV", "#2a78d6"], ["ev", "EV", "#0ca678"], ["ac", "AC", "#e8590c"]];
  var maxX = data[data.length - 1].offset;
  var maxY = Math.max.apply(null, data.map(function (p) { return Math.max(p.pv, p.ev || 0, p.ac || 0); })) * 1.05;
  var x = function (v) { return L + (W - L - R) * v / maxX; };
  var y = function (v) { return H - B - (H - T - B) * v / maxY; };
  var svg = '<svg width="' + W + '" height="' + H + '" role="img" aria-label="Planned value, earned value and actual cost over time">';
  for (var i = 0; i <= 4; i++) {
    var v = maxY * i / 4;
    svg += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y(v) + '" y2="' + y(v) + '" stroke="#e1e5ea"/>';
    svg += '<text x="' + (L - 8) + '" y="' + (y(v) + 4) + '" text-anchor="end" font-size="11" fill="#5d6877">' + (v / 1e6).toFixed(1) + 'M</text>';
  }
  var step = Math.ceil(data.length / 8);
  data.forEach(function (p, n) {
    if (n % step === 0) svg += '<text x="' + x(p.offset) + '" y="' + (H - 10) + '" text-anchor="middle" font-size="11" fill="#5d6877">' + p.date.slice(0, 6) + '</text>';
  });
  var labels = [];
  series.forEach(function (s) {
    var pts = data.filter(function (p) { return p[s[0]] !== null; });
    svg += '<polyline fill="none" stroke="' + s[2] + '" stroke-width="2" points="' + pts.map(function (p) { return x(p.offset) + "," + y(p[s[0]]); }).join(" ") + '"/>';
    var last = pts[pts.length - 1];
    labels.push({ text: s[1], x: x(last.offset) + 7, y: y(last[s[0]]) + 4 });
  });
  labels.sort(function (a, b) { return a.y - b.y; });
  labels.forEach(function (l, n) {
    if (n && Math.abs(l.x - labels[n - 1].x) < 30 && l.y - labels[n - 1].y < 14) l.y = labels[n - 1].y + 14;
    svg += '<text x="' + l.x + '" y="' + l.y + '" font-size="12" font-weight="600" fill="#1b2430" class="halo">' + l.text + '</text>';
  });
  svg += '<line class="cross" y1="' + T + '" y2="' + (H - B) + '" stroke="#5d6877" stroke-dasharray="3 3" style="display:none"/></svg>';
  host.innerHTML = svg + '<div class="tip"></div>';
  var tip = host.querySelector(".tip"), cross = host.querySelector(".cross");
  var money = function (v) { return v === null ? "-" : "PKR " + v.toLocaleString("en-US"); };
  host.addEventListener("mousemove", function (e) {
    var box = host.getBoundingClientRect(), mx = e.clientX - box.left, best = data[0];
    data.forEach(function (p) { if (Math.abs(x(p.offset) - mx) < Math.abs(x(best.offset) - mx)) best = p; });
    cross.setAttribute("x1", x(best.offset)); cross.setAttribute("x2", x(best.offset)); cross.style.display = "";
    tip.innerHTML = "<b>" + best.date + "</b><br>PV " + money(best.pv) + "<br>EV " + money(best.ev) + "<br>AC " + money(best.ac);
    tip.style.display = "block";
    tip.style.left = Math.min(x(best.offset) + 10, W - 190) + "px";
    tip.style.top = "20px";
  });
  host.addEventListener("mouseleave", function () { tip.style.display = "none"; cross.style.display = "none"; });
}
