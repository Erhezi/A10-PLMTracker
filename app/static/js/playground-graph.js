/* global d3 */

(function initPlaygroundGraph() {
  const dataTag = document.getElementById("playground-data");
  let data = null;
  if (dataTag && dataTag.textContent) {
    try {
      data = JSON.parse(dataTag.textContent);
    } catch (error) {
      console.error("Failed to parse playground graph data", error);
    }
  }

  if (!data || !data.nodes || !data.links) {
    return;
  }

  const container = document.getElementById("playground-graph");
  if (!container) {
    return;
  }

  const nodes = data.nodes.map((node) => ({ ...node }));
  const links = data.links.map((link) => ({ ...link }));

  const degreeMap = new Map();
  links.forEach((link) => {
    if (link.source) {
      degreeMap.set(link.source, (degreeMap.get(link.source) || 0) + 1);
    }
    if (link.target) {
      degreeMap.set(link.target, (degreeMap.get(link.target) || 0) + 1);
    }
  });

  const ROLE_LABELS = {
    origin: "Source",
    replacement: "Replacement",
    unknown: "Unknown",
  };

  const ROLE_COLORS = {
    source: "#f97316",
    target: "#3b82f6",
    both: "#a855f7",
    fallback: "#e5e7eb",
  };

  const toList = (value) => (Array.isArray(value) ? value : []);

  nodes.forEach((node) => {
    node.roles = toList(node.roles);
    node.stages = toList(node.stages);
    node.groups = toList(node.groups);
    node.descriptions = toList(node.descriptions);
    node.manufacturers = toList(node.manufacturers);

    node.degree = degreeMap.get(node.id) || 0;
    node.primaryStage = node.stages.length > 0 ? node.stages[0] : "Unspecified";
    node.primaryRole = node.roles.length > 0 ? node.roles[0] : "unknown";
    node.primaryDescription = node.descriptions.length > 0 ? node.descriptions[0] : null;
    node.primaryManufacturer = node.manufacturers.length > 0 ? node.manufacturers[0] : null;

    const primaryGroupValue = typeof node.primary_group === "number" ? node.primary_group : node.primary_group || null;
    node.groupKey = primaryGroupValue !== null && primaryGroupValue !== undefined ? String(primaryGroupValue) : "__ungrouped__";
    node.groupLabel = primaryGroupValue !== null && primaryGroupValue !== undefined ? `Group ${primaryGroupValue}` : "Ungrouped";

    node.isSourceOnly = node.roles.includes("origin") && !node.roles.includes("replacement");
    node.isTarget = node.roles.includes("replacement");
    node.isHybrid = node.roles.includes("origin") && node.roles.includes("replacement");
    node.isDraggable = node.isSourceOnly || node.isTarget || node.isHybrid;
  });

  const tooltip = document.createElement("div");
  tooltip.className = "playground-tooltip card shadow";
  tooltip.style.position = "fixed";
  tooltip.style.pointerEvents = "none";
  tooltip.style.opacity = "0";
  tooltip.style.transition = "opacity 0.2s ease";
  document.body.appendChild(tooltip);

  function showTooltip(event, node) {
    const groupSummary = node.groups.length > 0 ? node.groups.join(", ") : "(none)";
    const rolesSummary = node.roles.length > 0
      ? node.roles.map((role) => ROLE_LABELS[role] || role).join(", ")
      : ROLE_LABELS.unknown;
    const stageSummary = node.stages.length > 0 ? node.stages.join(", ") : "Unspecified";
    const description = node.primaryDescription || "Description unavailable";
    const manufacturer = node.primaryManufacturer || "Manufacturer unavailable";

    tooltip.innerHTML = `
      <div class="card-body p-2">
        <div class="fw-semibold text-primary">Item ${node.label}</div>
        <div class="small text-muted">Role: ${rolesSummary}</div>
        <div class="small text-muted">Stages: ${stageSummary}</div>
        <div class="small text-muted">Description: ${description}</div>
        <div class="small text-muted">Manufacturer: ${manufacturer}</div>
        <div class="small text-muted">Groups: ${groupSummary}</div>
        <div class="small text-muted">Connections: ${node.degree}</div>
      </div>
    `;
    const margin = 12;
    tooltip.style.left = `${event.clientX + margin}px`;
    tooltip.style.top = `${event.clientY + margin}px`;
    tooltip.style.opacity = "1";
  }

  function hideTooltip() {
    tooltip.style.opacity = "0";
  }

  const height = 600;
  let width = container.clientWidth || 960;

  const uniqueGroups = Array.from(new Set(nodes.map((node) => node.groupKey)));

  function computeGroupCenters(currentWidth, currentHeight) {
    const centers = new Map();
    if (uniqueGroups.length === 1) {
      centers.set(uniqueGroups[0], { x: currentWidth / 2, y: currentHeight / 2 });
      return centers;
    }

    const columns = Math.ceil(Math.sqrt(uniqueGroups.length));
    const rows = Math.ceil(uniqueGroups.length / columns);
    const cellWidth = currentWidth / columns;
    const cellHeight = currentHeight / rows;
    uniqueGroups.forEach((groupKey, index) => {
      const column = index % columns;
      const row = Math.floor(index / columns);
      const x = cellWidth * (column + 0.5);
      const y = cellHeight * (row + 0.5);
      centers.set(groupKey, { x, y });
    });
    return centers;
  }

  let groupCenters = computeGroupCenters(width, height);

  const svg = d3
    .select(container)
    .append("svg")
    .attr("class", "playground-graph-svg")
    .attr("width", "100%")
    .attr("height", "100%")
    .attr("height", height)
    .attr("viewBox", `0 0 ${width} ${height}`)
    .attr("preserveAspectRatio", "xMidYMid meet");

  const defs = svg.append("defs");
  const gradient = defs
    .append("radialGradient")
    .attr("id", "playground-background")
    .attr("cx", "50%")
    .attr("cy", "50%")
    .attr("r", "75%");
  gradient.append("stop").attr("offset", "0%").attr("stop-color", "#111827").attr("stop-opacity", 0.9);
  gradient.append("stop").attr("offset", "100%").attr("stop-color", "#1f2937").attr("stop-opacity", 0.8);

  const glowFilter = defs.append("filter").attr("id", "node-glow");
  glowFilter.append("feGaussianBlur").attr("stdDeviation", "5").attr("result", "coloredBlur");
  const feMerge = glowFilter.append("feMerge");
  feMerge.append("feMergeNode").attr("in", "coloredBlur");
  feMerge.append("feMergeNode").attr("in", "SourceGraphic");

  svg
    .append("rect")
    .attr("width", width)
    .attr("height", height)
    .attr("fill", "url(#playground-background)");

  const zoomLayer = svg.append("g");

  const link = zoomLayer
    .append("g")
    .attr("stroke", "#a5b4fc")
    .attr("stroke-opacity", 0.55)
    .attr("stroke-width", 2.1)
    .attr("stroke-linecap", "round")
    .selectAll("line")
    .data(links)
    .join("line")
    .attr("marker-end", "url(#arrowhead)");

  const arrowMarker = defs
    .append("marker")
    .attr("id", "arrowhead")
    .attr("viewBox", "0 -5 10 10")
    .attr("refX", 20)
    .attr("refY", 0)
    .attr("orient", "auto")
    .attr("markerWidth", 6)
    .attr("markerHeight", 6);
  arrowMarker
    .append("path")
    .attr("d", "M0,-5L10,0L0,5")
    .attr("fill", "#cdd5faff")
    .attr("fill-opacity", 0.7);

  const dragBehaviour = d3
    .drag()
    .filter((event, node) => !!node.isDraggable)
    .on("start", function (event, node) {
      if (event.sourceEvent && typeof event.sourceEvent.stopPropagation === "function") {
        event.sourceEvent.stopPropagation();
      }
      if (!event.active) simulation.alphaTarget(0.3).restart();
      node.fx = node.x;
      node.fy = node.y;
      d3.select(this).style("cursor", "grabbing");
    })
    .on("drag", function (event, node) {
      node.fx = event.x;
      node.fy = event.y;
    })
    .on("end", function (event, node) {
      if (!event.active) simulation.alphaTarget(0);
      node.fx = null;
      node.fy = null;
      d3.select(this).style("cursor", node.isDraggable ? "grab" : "default");
    });

  const nodeGroup = zoomLayer
    .append("g")
    .attr("stroke", "rgba(15, 23, 42, 0.6)")
    .attr("stroke-width", 1)
    .selectAll("g")
    .data(nodes)
    .join("g")
    .style("cursor", (node) => (node.isDraggable ? "grab" : "default"))
    .on("mouseenter", function (event, node) {
      d3.select(this).select("circle").attr("stroke-width", 2);
      showTooltip(event, node);
    })
    .on("mousemove", showTooltip)
    .on("mouseleave", function (event, node) {
      d3.select(this).select("circle").attr("stroke-width", 0.001);
      d3.select(this).style("cursor", node.isDraggable ? "grab" : "default");
      hideTooltip();
    })
    .call(dragBehaviour);

  function nodeFillColour(node) {
    if (node.isSourceOnly) return ROLE_COLORS.source;
    if (node.isHybrid) return ROLE_COLORS.both;
    if (node.isTarget) return ROLE_COLORS.target;
    return ROLE_COLORS.fallback;
  }

  nodeGroup
    .append("circle")
    .attr("r", (node) => 14 + Math.min(node.degree, 6) * 2.1)
    .attr("fill", nodeFillColour)
    .attr("fill-opacity", 1)
    .attr("stroke", nodeFillColour)
    .attr("stroke-width", 0.001);

  const nodeLabelSelection = nodeGroup
    .append("text")
    .attr("class", "playground-node-label")
    .attr("text-anchor", "middle")
    .attr("dy", 4)
    .attr("fill", "#ffffff")
    .attr("stroke", "none")
  .attr("font-size", "0.9rem")
    .attr("font-weight", 600)
    .style("paint-order", "fill")
    .text((node) => node.label);

  nodeLabelSelection.style("display", "none");

  const labelToggle = document.getElementById("toggle-node-labels");
  if (labelToggle) {
    const updateLabelVisibility = () => {
      const showLabels = labelToggle.checked;
      nodeLabelSelection.style("display", showLabels ? null : "none");
    };
    labelToggle.addEventListener("change", updateLabelVisibility);
    updateLabelVisibility();
  }

  const simulation = d3
    .forceSimulation(nodes)
    .force(
      "link",
      d3
        .forceLink(links)
        .id((node) => node.id)
        .distance((link) => {
          const base = 70;
          const sourceKey = typeof link.source === "object" ? link.source.id : link.source;
          const targetKey = typeof link.target === "object" ? link.target.id : link.target;
          const sourceDegree = Math.min(degreeMap.get(sourceKey) || 0, 6);
          const targetDegree = Math.min(degreeMap.get(targetKey) || 0, 6);
          return base + (sourceDegree + targetDegree) * 8;
        })
        .strength(0.3)
    )
    .force("charge", d3.forceManyBody().strength(-140))
    .force(
      "collide",
  d3.forceCollide().radius((node) => 30 + Math.min(node.degree, 8) * 2.8).strength(0.8)
    )
    .force(
      "clusterX",
      d3.forceX((node) => {
        const center = groupCenters.get(node.groupKey) || { x: width / 2, y: height / 2 };
        return center.x;
      }).strength(0.35)
    )
    .force(
      "clusterY",
      d3.forceY((node) => {
        const center = groupCenters.get(node.groupKey) || { x: width / 2, y: height / 2 };
        return center.y;
      }).strength(0.35)
    )
    .on("tick", ticked);

  function ticked() {
    link
      .attr("x1", (link) => link.source.x)
      .attr("y1", (link) => link.source.y)
      .attr("x2", (link) => link.target.x)
      .attr("y2", (link) => link.target.y);

    nodeGroup.attr("transform", (node) => `translate(${node.x}, ${node.y})`);
  }

  const zoomBehaviour = d3
    .zoom()
    .scaleExtent([0.5, 3])
    .on("zoom", (event) => {
      zoomLayer.attr("transform", event.transform);
    });

  const initialScale = 0.8;

  function computeDefaultTransform() {
    return d3.zoomIdentity
      .translate((width * (1 - initialScale)) / 2, (height * (1 - initialScale)) / 2)
      .scale(initialScale);
  }

  function applyDefaultTransform(withAnimation = false) {
    const transform = computeDefaultTransform();
    if (withAnimation) {
      svg.transition().duration(450).call(zoomBehaviour.transform, transform);
    } else {
      svg.call(zoomBehaviour.transform, transform);
    }
  }

  svg.call(zoomBehaviour);
  applyDefaultTransform(false);

  svg.on("dblclick.zoom", null).on("dblclick", (event) => {
    event.preventDefault();
    applyDefaultTransform(true);
  });

  const roleLegendEntries = [
    {
      key: "source",
      label: "Original Item",
      color: ROLE_COLORS.source,
      present: nodes.some((node) => node.isSourceOnly),
    },
    {
      key: "target",
      label: "Replacement Item",
      color: ROLE_COLORS.target,
      present: nodes.some((node) => node.isTarget && !node.isSourceOnly && !node.isHybrid),
    },
    {
      key: "hybrid",
      label: "Source + Replacement",
      color: ROLE_COLORS.both,
      present: nodes.some((node) => node.isHybrid),
    },
  ].filter((entry) => entry.present);

  let legendGroup = null;
  let legendWidth = 0;
  let legendHeight = 0;

  const legendContainer = document.getElementById("playground-legend");
  const legendWrapper = legendContainer ? legendContainer.closest(".playground-legend-wrapper") : null;
  const legendShell = legendContainer ? legendContainer.closest(".playground-legend-shell") : null;
  const originalLegendMaxHeight = legendContainer ? legendContainer.style.maxHeight : "";

  if (legendContainer) {
    legendContainer.classList.add("playground-legend-root");
    legendContainer.innerHTML = "";

    if (roleLegendEntries.length > 0) {
      const nodeLegendCard = document.createElement("div");
      nodeLegendCard.className = "border-bottom playground-legend-card px-3 pt-2 pb-1";
      const title = document.createElement("div");
      title.className = "text-uppercase small text-muted fw-semibold mb-2 playground-legend-title";
      title.textContent = "Node types";
      nodeLegendCard.appendChild(title);

      roleLegendEntries.forEach((entry) => {
        const row = document.createElement("div");
        row.className = "d-flex align-items-center mb-2 playground-legend-row";
        const swatch = document.createElement("span");
        swatch.className = "me-2 rounded-circle";
        swatch.style.display = "inline-block";
        swatch.style.width = "12px";
        swatch.style.height = "12px";
        swatch.style.backgroundColor = entry.color;
        row.appendChild(swatch);
        const label = document.createElement("span");
        label.className = "small";
        label.textContent = entry.label;
        row.appendChild(label);
        nodeLegendCard.appendChild(row);
      });

      legendContainer.appendChild(nodeLegendCard);
    }

    const groupsCard = document.createElement("div");
    groupsCard.className = "playground-legend-card d-flex flex-column flex-grow-1 px-3 pt-2 pb-0";
    const groupsTitle = document.createElement("div");
    groupsTitle.className = "text-uppercase small text-muted fw-semibold mb-2 playground-legend-title";
    groupsTitle.textContent = "Item groups";
    groupsCard.appendChild(groupsTitle);

    if (uniqueGroups.length === 0) {
      const empty = document.createElement("p");
      empty.className = "small text-muted mb-0";
      empty.textContent = "No groups found in current slice.";
      groupsCard.appendChild(empty);
    } else {
      const list = document.createElement("ul");
      list.className = "list-unstyled small mb-0";
      uniqueGroups.forEach((groupKey) => {
        const li = document.createElement("li");
        li.className = "mb-1";
        if (groupKey === "__ungrouped__") {
          li.textContent = "Ungrouped items";
        } else {
          li.textContent = `Group ${groupKey}`;
        }
        list.appendChild(li);
      });
      const scrollWrap = document.createElement("div");
      scrollWrap.className = "playground-legend-group-scroll flex-grow-1";
      scrollWrap.appendChild(list);
      groupsCard.appendChild(scrollWrap);
    }

    legendContainer.appendChild(groupsCard);
  }

  const desktopMediaQuery = window.matchMedia("(min-width: 992px)");

  function applyLegendHeightConstraints() {
    const targetHeight = `${height}px`;
    if (desktopMediaQuery.matches) {
      container.style.height = targetHeight;
      if (legendWrapper) {
        legendWrapper.style.height = targetHeight;
        legendWrapper.style.minHeight = targetHeight;
      }
      if (legendShell) {
        legendShell.style.height = targetHeight;
        legendShell.style.minHeight = targetHeight;
      }
      if (legendContainer) {
        legendContainer.style.boxSizing = "border-box";
        legendContainer.style.height = targetHeight;
        legendContainer.style.minHeight = targetHeight;
        legendContainer.style.maxHeight = targetHeight;
      }
    } else {
      container.style.height = "";
      if (legendWrapper) {
        legendWrapper.style.height = "";
        legendWrapper.style.minHeight = "";
      }
      if (legendShell) {
        legendShell.style.height = "";
        legendShell.style.minHeight = "";
      }
      if (legendContainer) {
        legendContainer.style.height = "";
        legendContainer.style.minHeight = "";
        legendContainer.style.maxHeight = originalLegendMaxHeight;
      }
    }
  }

  applyLegendHeightConstraints();

  if (typeof desktopMediaQuery.addEventListener === "function") {
    desktopMediaQuery.addEventListener("change", applyLegendHeightConstraints);
  } else if (typeof desktopMediaQuery.addListener === "function") {
    desktopMediaQuery.addListener(applyLegendHeightConstraints);
  }

  const resizeObserver = new ResizeObserver((entries) => {
    for (const entry of entries) {
      if (entry.contentRect && entry.contentRect.width) {
        width = entry.contentRect.width;
        svg.attr("viewBox", `0 0 ${width} ${height}`);
        svg.select("rect").attr("width", width);
        groupCenters = computeGroupCenters(width, height);
        simulation.alpha(0.35).restart();
      }
    }
  });

  resizeObserver.observe(container);
})();
