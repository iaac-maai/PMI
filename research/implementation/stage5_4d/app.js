"use strict";

const byId = id => document.getElementById(id);
const minute = 60_000;
const day = 1440 * minute;
const svgNS = "http://www.w3.org/2000/svg";
const formatDate = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/Madrid", day: "2-digit", month: "short",
  hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});
const date = milliseconds => formatDate.format(milliseconds);
const time = value => Date.parse(value);
const camera = {eye: {x: 1.45, y: -1.7, z: 1.25}, center: {x: 0, y: 0, z: 0}};
const categories = {
  productive: ["work", "Construction"],
  inspection: ["inspect", "Inspection"],
  elapsed_hold: ["hold", "Curing hold"],
  strength_release: ["hold", "Strength release"],
};

function svg(tag, attributes, parent, content) {
  const node = document.createElementNS(svgNS, tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  if (content !== undefined) node.textContent = content;
  parent.append(node);
  return node;
}

function setup(workspace) {
  const {viewer, elements, proof, origin} = workspace;
  const activities = viewer.activities_by_id;
  const entries = Object.entries(activities);
  const reverse = viewer.activity_ids_by_element_global_id;
  const models = Object.entries(elements);
  const beginning = Math.min(...entries.map(([, row]) => time(row.cp_sat.start)));
  const ending = Math.max(...entries.map(([, row]) => time(row.cp_sat.finish)));
  const totalMinutes = (ending - beginning) / minute;
  const state = {mode: "cp_sat", filter: "", element: null, activity: null, offset: 0, playing: false};
  const visibleRows = new Map();
  const elementButtons = new Map();
  const graph = byId("model");
  const scrub = byId("scrub");
  let playhead, frame, previousFrame, meshColors = [];

  byId("origin").textContent = origin;
  byId("proof").textContent = `${proof.status} · ${proof.project_makespan_minutes.toLocaleString("en-GB")} min · bound ${proof.lower_bound_minutes.toLocaleString("en-GB")} min`;
  scrub.max = totalMinutes;
  byId("workspace").hidden = false;

  for (const pack of viewer.packages) {
    byId("package").add(new Option(pack.family, pack.id));
  }
  for (const [gid, model] of models) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = model.name || model.ifc_class;
    button.dataset.gid = gid;
    button.addEventListener("click", () => selectElement(gid));
    byId("elements").append(button);
    elementButtons.set(gid, button);
  }

  function selectElement(gid) {
    if (!Object.hasOwn(elements, gid)) return;
    state.element = gid;
    state.activity = null;
    if (state.filter && !reverse[gid].some(id => activities[id].package_id === state.filter)) {
      setFilter("");
    }
    update();
  }

  function selectActivity(id) {
    state.activity = id;
    state.element = activities[id].element_global_ids[0];
    update();
  }

  function setFilter(value) {
    state.filter = value;
    byId("package").value = value;
    drawTimeline();
  }

  const axisStart = 192;
  const axisEnd = 862;
  const x = instant => axisStart + (instant - beginning) / (ending - beginning) * (axisEnd - axisStart);

  function drawTimeline() {
    visibleRows.clear();
    const container = byId("gantt");
    container.replaceChildren();
    const packages = viewer.packages.filter(pack => !state.filter || pack.id === state.filter);
    const height = 39 + packages.reduce((count, pack) => count + 26 + 23 * pack.activity_ids.length, 0);
    const chart = svg("svg", {viewBox: `0 0 884 ${height}`, "aria-label": "Schedule timeline"}, container);
    const defs = svg("defs", {}, chart);
    const arrow = svg("marker", {id: "arrow", markerWidth: 6, markerHeight: 6,
      refX: 5, refY: 3, orient: "auto", markerUnits: "userSpaceOnUse"}, defs);
    svg("path", {d: "M0 0 L6 3 L0 6 Z", fill: "#687e96"}, arrow);
    svg("text", {x: 14, y: 24, fill: "#52677b"}, chart, "PACKAGE / ACTIVITY");
    for (let instant = beginning; instant <= ending; instant += 2 * day) {
      svg("line", {x1: x(instant), x2: x(instant), y1: 30, y2: height, stroke: "#dbe3ec"}, chart);
      svg("text", {x: x(instant) + 3, y: 24, fill: "#52677b"}, chart, date(instant).split(",")[0]);
    }
    const rowsLayer = svg("g", {}, chart);
    let y = 39;
    for (const pack of packages) {
      svg("rect", {x: 0, y, width: 884, height: 24, fill: "#e9eff5"}, rowsLayer);
      svg("text", {x: 13, y: y + 17, fill: "#27465f", "font-weight": 700}, rowsLayer, pack.family);
      y += 26;
      for (const id of pack.activity_ids) {
        const row = activities[id];
        const timing = row[state.mode];
        const [style, category] = categories[row.kind];
        const isCritical = state.mode === "cpm" && row.cpm.cpm_critical;
        const title = `${row.label} · ${category} · ${date(time(timing.start))} – ${date(time(timing.finish))}${isCritical ? " · CPM critical" : ""}`;
        const group = svg("g", {class: "row", role: "button", tabindex: 0,
          "aria-label": title, "data-id": id}, rowsLayer);
        svg("title", {}, group, title);
        svg("rect", {class: "stripe", x: 1, y, width: 881, height: 22}, group);
        svg("text", {x: 15, y: y + 16}, group, row.label);
        svg("text", {x: 120, y: y + 16, "font-size": 12}, group,
          style === "work" ? "Work" : style === "hold" ? "Hold" : "Inspect");
        const start = x(time(timing.start));
        const finish = x(time(timing.finish));
        svg("rect", {class: `bar ${style}${isCritical ? " critical" : ""}`, x: start, y: y + 5,
          width: Math.max(3, finish - start), height: 12, rx: 2}, group);
        group.addEventListener("click", () => selectActivity(id));
        group.addEventListener("keydown", event => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            selectActivity(id);
          }
        });
        visibleRows.set(id, {group, start, finish, y: y + 11});
        y += 23;
      }
    }
    for (const edge of viewer.dependencies) {
      const from = visibleRows.get(edge.predecessor_id);
      const to = visibleRows.get(edge.successor_id);
      if (!from || !to) continue;
      const turn = Math.max(from.finish + 4, (from.finish + to.start) / 2);
      svg("path", {d: `M${from.finish},${from.y} H${turn} V${to.y} H${to.start}`,
        class: "edge", "marker-end": "url(#arrow)"}, chart);
    }
    playhead = svg("line", {class: "playhead", y1: 30, y2: height}, chart);
  }

  function update() {
    const instant = beginning + state.offset * minute;
    const activityStates = new Map(entries.map(([id, row]) => {
      const t = row.cp_sat;
      const active = t.segments.some(([start, finish]) => time(start) <= instant && instant < time(finish));
      return [id, instant >= time(t.finish) ? "complete" : active ? "active" : "upcoming"];
    }));
    const values = [...activityStates.values()];
    byId("active").textContent = `${values.filter(value => value === "active").length} active`;
    byId("complete").textContent = `${values.filter(value => value === "complete").length} completed`;
    scrub.value = Math.round(state.offset);
    byId("date").textContent = `${date(instant)} CET`;
    playhead.setAttribute("x1", x(instant));
    playhead.setAttribute("x2", x(instant));
    byId("cpm").setAttribute("aria-pressed", state.mode === "cpm");
    byId("cp_sat").setAttribute("aria-pressed", state.mode === "cp_sat");

    for (const [id, {group}] of visibleRows) {
      const linked = state.element && reverse[state.element].includes(id);
      group.classList.toggle("related", Boolean(linked));
      group.classList.toggle("selected", id === state.activity);
      group.classList.toggle("active", activityStates.get(id) === "active");
      group.classList.toggle("complete", activityStates.get(id) === "complete");
      group.setAttribute("aria-pressed", id === state.activity);
    }
    for (const [gid, button] of elementButtons) button.setAttribute("aria-pressed", gid === state.element);

    const picked = elements[state.element];
    byId("identity").textContent = picked
      ? `${picked.name || picked.ifc_class} · ${picked.ifc_class} · ${state.element} · ${reverse[state.element].length} activities`
      : "Select an IFC element or an activity to inspect its linked element.";
    const row = activities[state.activity];
    const timing = row?.[state.mode];
    byId("activity").textContent = row
      ? `${row.label} · ${categories[row.kind][1]} · ${date(time(timing.start))} – ${date(time(timing.finish))} CET · ${activityStates.get(state.activity)}`
      : "Select an activity for its exact start and finish times.";

    const colors = models.map(([gid]) => {
      if (gid === state.element) return "#12b5a6";
      const linked = reverse[gid].map(id => activityStates.get(id));
      if (linked.includes("active")) return "#e7a33c";
      if (linked.every(value => value === "complete")) return "#4e9a78";
      return "#7796b5";
    });
    if (graph.data && colors.some((color, index) => color !== meshColors[index])) {
      meshColors = colors;
      Plotly.restyle(graph, {color: colors});
    }
  }

  function stop() {
    state.playing = false;
    cancelAnimationFrame(frame);
    byId("play").textContent = "Play";
  }

  function animate(now) {
    if (!state.playing) return;
    const delta = now - previousFrame;
    previousFrame = now;
    state.offset = Math.min(totalMinutes, state.offset + delta / 1000 * 420 * Number(byId("speed").value));
    update();
    if (state.offset === totalMinutes) stop();
    else frame = requestAnimationFrame(animate);
  }

  byId("play").onclick = () => {
    if (state.playing) { stop(); return; }
    if (state.offset === totalMinutes) state.offset = 0;
    state.playing = true;
    previousFrame = performance.now();
    byId("play").textContent = "Pause";
    frame = requestAnimationFrame(animate);
  };
  scrub.oninput = () => { state.offset = Number(scrub.value); update(); };
  byId("package").onchange = event => { setFilter(event.target.value); update(); };
  for (const mode of ["cpm", "cp_sat"]) {
    byId(mode).onclick = () => { state.mode = mode; drawTimeline(); update(); };
  }
  byId("clear").onclick = () => { state.element = null; state.activity = null; update(); };
  function zoom(factor) {
    const eye = graph.layout?.scene.camera?.eye;
    if (!eye) return;
    const distance = Math.hypot(eye.x, eye.y, eye.z);
    if (distance * factor < 0.55 || distance * factor > 6) return;
    Plotly.relayout(graph, {"scene.camera.eye": {x: eye.x * factor, y: eye.y * factor, z: eye.z * factor}});
  }
  byId("zoom-in").onclick = () => zoom(0.82);
  byId("zoom-out").onclick = () => zoom(1 / 0.82);
  byId("reset").onclick = () => Plotly.relayout(graph, {"scene.camera": camera});
  drawTimeline();
  update();

  const traces = models.map(([gid, mesh]) => ({
    type: "mesh3d", name: mesh.name || mesh.ifc_class, meta: gid, flatshading: true,
    x: mesh.vertices.map(vertex => vertex[0]), y: mesh.vertices.map(vertex => vertex[1]),
    z: mesh.vertices.map(vertex => vertex[2]), i: mesh.faces.map(face => face[0]),
    j: mesh.faces.map(face => face[1]), k: mesh.faces.map(face => face[2]),
    color: "#7796b5", hovertemplate: `%{fullData.name}<extra></extra>`,
    lighting: {ambient: 0.63, diffuse: 0.75, specular: 0.17, roughness: 0.7},
  }));
  return Plotly.newPlot(graph, traces, {
    margin: {l: 0, r: 0, b: 0, t: 5}, paper_bgcolor: "#f1f6fa", uirevision: "r0",
    scene: {aspectmode: "data", camera, bgcolor: "#f1f6fa",
      xaxis: {title: {text: "X (m)"}}, yaxis: {title: {text: "Y (m)"}}, zaxis: {title: {text: "Z (m)"}}},
  }, {responsive: true, scrollZoom: true, displayModeBar: true, displaylogo: false}).then(() => {
    graph.on("plotly_click", event => {
      const index = event.points[0]?.curveNumber;
      if (index !== undefined) selectElement(graph.data[index].meta);
    });
    update();
  });
}

fetch("/data.json").then(response => {
  if (!response.ok) throw new Error("Verified workspace data is unavailable.");
  return response.json();
}).then(workspace => {
  if (workspace.contract_version !== "pmi-r0-prototype/1") throw new Error("Unsupported workspace contract.");
  return setup(workspace);
}).catch(error => {
  byId("workspace").hidden = true;
  byId("error").textContent = error.message;
});
