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

  const animationToggle = document.getElementById("toggle-animation");
  const ANIMATION_STORAGE_KEY = "playgroundAnimationEnabled";
  let storedAnimationPreference = null;

  if (animationToggle) {
    try {
      storedAnimationPreference = window.localStorage.getItem(ANIMATION_STORAGE_KEY);
      if (storedAnimationPreference !== null) {
        animationToggle.checked = storedAnimationPreference === "1";
        storedAnimationPreference = animationToggle.checked ? "1" : "0";
      }
    } catch (storageError) {
      console.warn("Unable to access animation preference storage", storageError);
      storedAnimationPreference = null;
    }
  }

  let animationEnabled = animationToggle ? animationToggle.checked : true;

  const nodes = data.nodes.map((node) => ({ ...node }));
  const links = data.links.map((link) => ({ ...link }));
  const applyQuantityEnabled = Boolean(data.meta && data.meta.apply_quantity);
  const quantityLocationCode = data.meta && data.meta.selected_location ? data.meta.selected_location : null;
  const quantityLocationLabel = data.meta && data.meta.selected_location_label ? data.meta.selected_location_label : null;
  const positiveQuantities = [];

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
    source: "#e93b8d",
    target: "#3f87b9",
    both: "#a855f7",
    fallback: "#e5e7eb",
  };

  const toList = (value) => (Array.isArray(value) ? value : []);

  function compareGroupKeys(a, b) {
    const aIsUngrouped = a === "__ungrouped__";
    const bIsUngrouped = b === "__ungrouped__";
    if (aIsUngrouped || bIsUngrouped) {
      return aIsUngrouped ? 1 : -1;
    }

    const aNum = Number(a);
    const bNum = Number(b);
    const aIsNum = Number.isFinite(aNum);
    const bIsNum = Number.isFinite(bNum);

    if (aIsNum && bIsNum) {
      if (aNum !== bNum) {
        return aNum - bNum;
      }
      return 0;
    }
    if (aIsNum) {
      return -1;
    }
    if (bIsNum) {
      return 1;
    }
    return String(a).localeCompare(String(b));
  }

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

    if (applyQuantityEnabled) {
      let availableQuantity = null;
      if (typeof node.available_quantity === "number") {
        availableQuantity = node.available_quantity;
      } else if (node.available_quantity !== null && node.available_quantity !== undefined) {
        const parsedQuantity = Number(node.available_quantity);
        availableQuantity = Number.isFinite(parsedQuantity) ? parsedQuantity : null;
      }
      node.availableQuantity = availableQuantity;
      if (typeof availableQuantity === "number" && availableQuantity > 0) {
        positiveQuantities.push(availableQuantity);
      }
    } else {
      node.availableQuantity = null;
    }
  });

  const hasPositiveQuantities = applyQuantityEnabled && positiveQuantities.length > 0;
  const maxPositiveQuantity = hasPositiveQuantities ? d3.max(positiveQuantities) : null;
  const quantityScale = hasPositiveQuantities && maxPositiveQuantity && maxPositiveQuantity > 1
    ? d3.scaleLog().domain([1, maxPositiveQuantity]).range([1, 5])
    : null;

  const ZERO_QUANTITY_RADIUS = 6;
  const QUANTITY_RADIUS_BASE = 10;
  const QUANTITY_RADIUS_STEP = 4;

  function getDefaultRadius(node) {
    return 14 + Math.min(node.degree, 6) * 2.1;
  }

  function computeQuantityBucket(node) {
    if (!applyQuantityEnabled) {
      return null;
    }
    if (node.availableQuantity === null || node.availableQuantity === undefined) {
      return null;
    }
    if (node.availableQuantity <= 0) {
      return 0;
    }
    if (!maxPositiveQuantity || maxPositiveQuantity <= 1 || !quantityScale) {
      return 1;
    }
    const scaledValue = quantityScale(Math.max(node.availableQuantity, 1));
    const bucket = Math.round(scaledValue);
    return Math.max(1, Math.min(5, bucket));
  }

  function computeRenderRadius(node) {
    if (!applyQuantityEnabled) {
      return getDefaultRadius(node);
    }
    if (node.availableQuantity === null || node.availableQuantity === undefined) {
      return getDefaultRadius(node);
    }
    if (node.availableQuantity <= 0) {
      return ZERO_QUANTITY_RADIUS;
    }
    const bucket = node.quantityBucket || computeQuantityBucket(node) || 1;
    return QUANTITY_RADIUS_BASE + bucket * QUANTITY_RADIUS_STEP;
  }

  function nodeRoleColour(node) {
    if (node.isSourceOnly) return ROLE_COLORS.source;
    if (node.isHybrid) return ROLE_COLORS.both;
    if (node.isTarget) return ROLE_COLORS.target;
    return ROLE_COLORS.fallback;
  }

  function nodeFillOpacity(node) {
    if (applyQuantityEnabled && node.availableQuantity !== null && node.availableQuantity !== undefined) {
      if (node.availableQuantity <= 0) {
        return 0;
      }
    }
    return 1;
  }

  function nodeStrokeWidth(node) {
    if (applyQuantityEnabled && node.availableQuantity !== null && node.availableQuantity !== undefined) {
      if (node.availableQuantity <= 0) {
        return 2;
      }
    }
    return 0.001;
  }

  function nodeStrokeColour(node) {
    return nodeRoleColour(node);
  }

  nodes.forEach((node) => {
    node.quantityBucket = computeQuantityBucket(node);
    node.renderRadius = computeRenderRadius(node);
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
    let quantityRow = "";
    if (applyQuantityEnabled) {
      const locationLabel = quantityLocationLabel || quantityLocationCode;
      const locationSuffix = locationLabel ? ` @ ${locationLabel}` : "";
      const quantityValueText = node.availableQuantity === null || node.availableQuantity === undefined
        ? "Not available"
        : node.availableQuantity;
      quantityRow = `<div class="small text-muted">Available Qty${locationSuffix}: ${quantityValueText}</div>`;
    }

    tooltip.innerHTML = `
      <div class="card-body p-2">
        <div class="fw-semibold text-primary">Item ${node.label}</div>
        <div class="small text-muted">Role: ${rolesSummary}</div>
        <div class="small text-muted">Stages: ${stageSummary}</div>
        <div class="small text-muted">Description: ${description}</div>
        <div class="small text-muted">Manufacturer: ${manufacturer}</div>
        <div class="small text-muted">Groups: ${groupSummary}</div>
        <div class="small text-muted">Connections: ${node.degree}</div>
        ${quantityRow}
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

  const uniqueGroups = Array.from(new Set(nodes.map((node) => node.groupKey))).sort(compareGroupKeys);

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
      if (animationEnabled) {
        if (!event.active) simulation.alphaTarget(0.3).restart();
      } else {
        simulation.stop();
      }
      node.fx = node.x;
      node.fy = node.y;
      d3.select(this).style("cursor", "grabbing");
    })
    .on("drag", function (event, node) {
      node.fx = event.x;
      node.fy = event.y;
      node.x = event.x;
      node.y = event.y;
      if (!animationEnabled) {
        ticked();
      }
    })
    .on("end", function (event, node) {
      if (animationEnabled) {
        if (!event.active) simulation.alphaTarget(0);
        node.fx = null;
        node.fy = null;
      } else {
        node.fx = null;
        node.fy = null;
        ticked();
      }
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
      const circle = d3.select(this).select("circle");
      circle.attr("stroke-width", Math.max(nodeStrokeWidth(node), 2));
      showTooltip(event, node);
    })
    .on("mousemove", showTooltip)
    .on("mouseleave", function (event, node) {
      const circle = d3.select(this).select("circle");
      circle.attr("stroke-width", nodeStrokeWidth(node));
      d3.select(this).style("cursor", node.isDraggable ? "grab" : "default");
      hideTooltip();
    })
    .call(dragBehaviour);

  nodeGroup
    .append("circle")
    .attr("r", (node) => node.renderRadius || getDefaultRadius(node))
    .attr("fill", nodeRoleColour)
    .attr("fill-opacity", (node) => nodeFillOpacity(node))
    .attr("stroke", nodeStrokeColour)
    .attr("stroke-width", (node) => nodeStrokeWidth(node));

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
      d3.forceCollide()
        .radius((node) => {
          if (applyQuantityEnabled && typeof node.renderRadius === "number") {
            return node.renderRadius + 18;
          }
          return 30 + Math.min(node.degree, 8) * 2.8;
        })
        .strength(0.8)
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

  simulation.on("end", () => {
    fitViewToNodes(animationEnabled);
  });

  function settleSimulation(iterations = 160) {
    simulation.alpha(1);
    for (let i = 0; i < iterations; i += 1) {
      simulation.tick();
    }
    ticked();
    simulation.alpha(0);
    simulation.stop();
    fitViewToNodes(false);
  }

  function setAnimationEnabled(enabled) {
    if (enabled === animationEnabled) {
      return;
    }
    animationEnabled = enabled;
    if (enabled) {
      simulation.alpha(1).restart();
    } else {
      settleSimulation();
    }
  }

  function ticked() {
    link
      .attr("x1", (link) => link.source.x)
      .attr("y1", (link) => link.source.y)
      .attr("x2", (link) => link.target.x)
      .attr("y2", (link) => link.target.y);

    nodeGroup.attr("transform", (node) => `translate(${node.x}, ${node.y})`);
  }

  if (animationToggle) {
    animationToggle.addEventListener("change", (event) => {
      const enabled = event.target.checked;
      setAnimationEnabled(enabled);
      try {
        window.localStorage.setItem(ANIMATION_STORAGE_KEY, enabled ? "1" : "0");
        storedAnimationPreference = enabled ? "1" : "0";
      } catch (storageError) {
        console.warn("Unable to persist animation preference", storageError);
      }
    });
  }

  const zoomBehaviour = d3
    .zoom()
    .scaleExtent([0.5, 3])
    .on("zoom", (event) => {
      zoomLayer.attr("transform", event.transform);
    });
  const ZOOM_FIT_PADDING = 60;
  const ZOOM_ANIMATION_MS = 450;

  function fitViewToNodes(withAnimation = false) {
    if (!nodes.length) {
      return;
    }

    const positionedNodes = nodes.filter((node) => Number.isFinite(node.x) && Number.isFinite(node.y));
    if (positionedNodes.length === 0) {
      return;
    }

    const minX = d3.min(positionedNodes, (node) => node.x);
    const maxX = d3.max(positionedNodes, (node) => node.x);
    const minY = d3.min(positionedNodes, (node) => node.y);
    const maxY = d3.max(positionedNodes, (node) => node.y);

    if (!Number.isFinite(minX) || !Number.isFinite(maxX) || !Number.isFinite(minY) || !Number.isFinite(maxY)) {
      return;
    }

    const contentWidth = Math.max(maxX - minX, 1);
    const contentHeight = Math.max(maxY - minY, 1);
    const paddedWidth = contentWidth + ZOOM_FIT_PADDING * 2;
    const paddedHeight = contentHeight + ZOOM_FIT_PADDING * 2;

    const [minScale, maxScale] = zoomBehaviour.scaleExtent();
    const fitScale = Math.min(width / paddedWidth, height / paddedHeight);
    const boundedScale = Math.max(minScale, Math.min(maxScale, fitScale));

    const centerX = (minX + maxX) / 2;
    const centerY = (minY + maxY) / 2;

    const transform = d3.zoomIdentity
      .translate(width / 2, height / 2)
      .scale(boundedScale)
      .translate(-centerX, -centerY);

    if (withAnimation) {
      svg.transition().duration(ZOOM_ANIMATION_MS).call(zoomBehaviour.transform, transform);
    } else {
      svg.call(zoomBehaviour.transform, transform);
    }
  }

  svg.call(zoomBehaviour);
  fitViewToNodes(false);

  svg.on("dblclick.zoom", null).on("dblclick", (event) => {
    event.preventDefault();
    fitViewToNodes(true);
  });

  if (!animationEnabled) {
    settleSimulation();
  }

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
        if (animationEnabled) {
          simulation.alpha(0.35).restart();
        } else {
          settleSimulation();
        }
        fitViewToNodes(false);
      }
    }
  });

  resizeObserver.observe(container);
})();
