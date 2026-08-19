(function () {
  "use strict";

  const data = window.PAPER_READER_DATA;
  const validation = window.PAPER_READER_VALIDATION || {};
  const runInfo = window.PAPER_READER_RUN || {};
  if (!data || !data.paper || !Array.isArray(data.paper.pages)) {
    document.body.textContent = "阅读器数据缺失或格式错误。";
    return;
  }

  const categories = {
    context: { label: "背景与定义", color: "#6285b4" },
    evidence: { label: "证据与结果", color: "#5d9678" },
    technical: { label: "公式与方法", color: "#806eae" },
    caveat: { label: "限定与风险", color: "#bd842f" }
  };
  const claimLabels = {
    direct: "原文直接陈述或数据直接显示",
    inference: "基于原文的有限推断",
    unknown: "尚未确认或证据不足"
  };
  const typeLabels = {
    text: "原文要点",
    figure: "图表讲解",
    table: "表格讲解",
    formula: "公式与推导",
    method: "方法与处理"
  };

  const pages = data.paper.pages;
  const notes = data.notes || { paper: {}, pages: {} };
  const translations = data.translations || { pages: {} };
  const title = (notes.paper && notes.paper.title) ||
    (data.paper.metadata && data.paper.metadata.title) || "论文全文阅读";

  const dom = Object.fromEntries([
    "paperTitle", "pageStatus", "readingViewMode", "figureViewMode", "formulaViewMode",
    "readingToolbar", "readingWorkspace", "explainerWorkspace", "originalMode", "bilingualMode",
    "previousPage", "nextPage", "pageSelect", "zoomSelect", "zoomControl", "sourcePdfLink",
    "sectionList", "markerMasterToggle", "markerFilters", "verificationSummary", "runMetricsSummary",
    "runMetrics", "translationStatus", "originalView",
    "bilingualView", "pageScroller", "pageCanvas", "pageImage", "markerLayer", "analysisPanel",
    "analysisCategory", "analysisTitle", "analysisContent", "backToPage", "questionToggle",
    "explainerCategory", "explainerTitle", "explainerLocator", "explainerNavigation",
    "explainerSourceFrame", "explainerSourceCanvas", "explainerTakeaway", "explainerSectionNav",
    "explainerContent", "openInReading", "openCropLarge", "questionWhole", "experimentalDataAction", "questionComposer",
    "questionContext", "questionInput", "askButton", "cancelQuestion", "questionStatus", "cropDialog",
    "cropDialogCanvas", "closeCropDialog"
  ].map(id => [id, document.getElementById(id)]));

  const hashParams = new URLSearchParams(location.hash.replace(/^#/, ""));
  const requestedPage = Number(hashParams.get("page"));
  const requestedMarker = hashParams.get("marker");
  const requestedView = hashParams.get("view");
  const requestedLanguage = hashParams.get("lang");
  const allowedViews = new Set(["reading", "figures", "formulas"]);
  const state = {
    page: Number.isInteger(requestedPage) && requestedPage >= 1 && requestedPage <= pages.length ? requestedPage : 1,
    viewMode: allowedViews.has(requestedView) ? requestedView : "reading",
    languageMode: requestedLanguage === "bilingual" ? "bilingual" : "original",
    zoom: 100,
    filters: new Set(Object.keys(categories)),
    selectedMarker: requestedMarker || null,
    explainerMarker: requestedMarker || null,
    questionTarget: null
  };

  function create(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function currentPage() { return pages[state.page - 1]; }
  function notesForPage(number) {
    return (notes.pages && notes.pages[String(number)]) || { overview: "", markers: [] };
  }
  function pageNotes() { return notesForPage(state.page); }
  function pageTranslation() {
    return (translations.pages && translations.pages[String(state.page)]) || { status: "missing", blocks: {} };
  }
  function allMarkers() {
    return Array.isArray(pageNotes().markers) ? pageNotes().markers : [];
  }
  function visibleMarkers() {
    return allMarkers().filter(marker => state.filters.has(marker.category || "context"));
  }
  function selectedMarker() {
    return allMarkers().find(marker => marker.id === state.selectedMarker) || null;
  }
  function experimentalDataInfo(marker) {
    const info = marker && marker.experimental_data;
    if (!info || typeof info !== "object") return null;
    return ["present", "uncertain"].includes(info.status) ? info : null;
  }
  function markerBlocks(marker, pageNumber = state.page) {
    const ids = Array.isArray(marker && marker.block_ids) ? marker.block_ids : [];
    const wanted = new Set(ids);
    const page = pages[pageNumber - 1];
    return page && Array.isArray(page.text_blocks) ? page.text_blocks.filter(block => wanted.has(block.id)) : [];
  }
  function boxesFor(marker) {
    const visual = marker.visual_bbox || marker.crop_bbox;
    if (["figure", "table", "formula"].includes(marker.content_type) && visual) return [visual];
    if (Array.isArray(marker.bboxes)) return marker.bboxes;
    if (marker.bbox && typeof marker.bbox === "object") return [marker.bbox];
    return visual ? [visual] : [];
  }
  function cropBoxFor(marker) {
    if (marker.visual_bbox || marker.crop_bbox) return marker.visual_bbox || marker.crop_bbox;
    const boxes = Array.isArray(marker.bboxes) ? marker.bboxes : (marker.bbox ? [marker.bbox] : []);
    if (!boxes.length) return null;
    return boxes.reduce((acc, box) => ({
      x0: Math.min(acc.x0, Number(box.x0)),
      y0: Math.min(acc.y0, Number(box.y0)),
      x1: Math.max(acc.x1, Number(box.x1)),
      y1: Math.max(acc.y1, Number(box.y1))
    }), { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity });
  }
  function globalMarkerRefs() {
    const refs = [];
    pages.forEach(page => {
      const pageEntry = notesForPage(page.number);
      (Array.isArray(pageEntry.markers) ? pageEntry.markers : []).forEach(marker => {
        refs.push({ marker, pageNumber: page.number, page });
      });
    });
    return refs;
  }
  function explainerItems(mode = state.viewMode) {
    return globalMarkerRefs().filter(ref => {
      if (!cropBoxFor(ref.marker)) return false;
      if (mode === "figures") return ["figure", "table"].includes(ref.marker.content_type);
      if (mode === "formulas") return ref.marker.content_type === "formula";
      return false;
    });
  }
  function activeExplainerRef() {
    const items = explainerItems();
    return items.find(ref => ref.marker.id === state.explainerMarker) || items[0] || null;
  }

  function setMode(mode) {
    state.languageMode = mode === "bilingual" ? "bilingual" : "original";
    dom.originalMode.classList.toggle("active", state.languageMode === "original");
    dom.bilingualMode.classList.toggle("active", state.languageMode === "bilingual");
    dom.originalMode.setAttribute("aria-pressed", String(state.languageMode === "original"));
    dom.bilingualMode.setAttribute("aria-pressed", String(state.languageMode === "bilingual"));
    dom.originalView.hidden = state.languageMode !== "original";
    dom.bilingualView.hidden = state.languageMode !== "bilingual";
    dom.zoomControl.hidden = state.languageMode !== "original";
    renderTranslationStatus();
    if (state.languageMode === "bilingual") renderBilingual();
    updateHash();
  }

  function setViewMode(mode, markerId) {
    state.viewMode = allowedViews.has(mode) ? mode : "reading";
    if (markerId) state.explainerMarker = markerId;
    if (state.viewMode !== "reading") {
      const items = explainerItems();
      if (!items.some(ref => ref.marker.id === state.explainerMarker)) {
        const samePage = items.find(ref => ref.pageNumber === state.page);
        state.explainerMarker = (samePage || items[0] || {}).marker?.id || null;
      }
    }
    const reading = state.viewMode === "reading";
    dom.readingWorkspace.hidden = !reading;
    dom.explainerWorkspace.hidden = reading;
    dom.readingToolbar.hidden = !reading;
    [
      [dom.readingViewMode, "reading"],
      [dom.figureViewMode, "figures"],
      [dom.formulaViewMode, "formulas"]
    ].forEach(([button, value]) => {
      const active = state.viewMode === value;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    closeQuestionComposer();
    if (reading) renderPage();
    else renderExplainer();
    updateHash();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function setPage(number) {
    state.page = Math.max(1, Math.min(pages.length, Number(number) || 1));
    state.selectedMarker = null;
    closeQuestionComposer();
    renderPage();
    updateHash();
    dom.pageScroller.scrollTop = 0;
    dom.pageScroller.scrollLeft = 0;
    dom.analysisPanel.scrollTop = 0;
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function setSelectedMarker(markerId) {
    state.selectedMarker = markerId;
    closeQuestionComposer();
    renderMarkers();
    renderAnalysis();
    updateHash();
    dom.analysisPanel.scrollTop = 0;
  }

  function clearMarkerSelection() {
    state.selectedMarker = null;
    closeQuestionComposer();
    renderMarkers();
    renderAnalysis();
    updateHash();
    dom.analysisPanel.scrollTop = 0;
  }

  function updateHash() {
    const params = new URLSearchParams();
    params.set("view", state.viewMode);
    params.set("page", String(state.page));
    if (state.viewMode === "reading") params.set("lang", state.languageMode);
    const marker = state.viewMode === "reading" ? state.selectedMarker : state.explainerMarker;
    if (marker) params.set("marker", marker);
    history.replaceState(null, "", `#${params.toString()}`);
  }

  function renderSections() {
    dom.sectionList.replaceChildren();
    let sections = notes.paper && Array.isArray(notes.paper.sections) ? notes.paper.sections : [];
    if (!sections.length) sections = [{ id: "full-paper", label: "全文", start_page: 1, end_page: pages.length }];
    sections.forEach(section => {
      const start = Math.max(1, Math.min(pages.length, Number(section.start_page) || 1));
      const end = Math.max(start, Math.min(pages.length, Number(section.end_page) || start));
      const button = create("button", "section-button");
      button.type = "button";
      button.classList.toggle("active", state.page >= start && state.page <= end);
      button.append(
        create("span", "", section.label || `第 ${start} 页`),
        create("span", "section-pages", start === end ? `p.${start}` : `p.${start}–${end}`)
      );
      button.addEventListener("click", () => setPage(start));
      dom.sectionList.append(button);
    });
  }

  function renderFilters() {
    dom.markerFilters.replaceChildren();
    Object.entries(categories).forEach(([key, meta]) => {
      const label = create("label", "filter-item");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = state.filters.has(key);
      input.addEventListener("change", () => {
        if (input.checked) state.filters.add(key);
        else {
          state.filters.delete(key);
          const active = selectedMarker();
          if (active && (active.category || "context") === key) state.selectedMarker = null;
        }
        renderMarkers();
        renderAnalysis();
        if (state.languageMode === "bilingual") renderBilingual();
        updateMasterFilterControl();
      });
      const swatch = create("span", "filter-swatch");
      swatch.style.setProperty("--swatch", meta.color);
      label.append(input, swatch, document.createTextNode(meta.label));
      dom.markerFilters.append(label);
    });
    updateMasterFilterControl();
  }

  function updateMasterFilterControl() {
    const anyVisible = state.filters.size > 0;
    dom.markerMasterToggle.textContent = anyVisible ? "隐藏全部标注" : "显示全部标注";
    dom.markerMasterToggle.setAttribute("aria-pressed", String(anyVisible));
  }

  function toggleAllMarkers() {
    if (state.filters.size) state.filters.clear();
    else Object.keys(categories).forEach(key => state.filters.add(key));
    state.selectedMarker = null;
    closeQuestionComposer();
    renderFilters();
    renderMarkers();
    renderAnalysis();
    if (state.languageMode === "bilingual") renderBilingual();
  }

  function renderMarkers() {
    dom.markerLayer.replaceChildren();
    const page = currentPage();
    visibleMarkers().forEach(marker => {
      boxesFor(marker).forEach((box, index) => {
        const button = create("button", `marker-box ${marker.category || "context"}`);
        button.type = "button";
        button.dataset.markerId = marker.id;
        button.setAttribute("aria-label", `${marker.title || "原文标注"}，位置 ${index + 1}`);
        button.classList.toggle("selected", marker.id === state.selectedMarker);
        button.style.left = `${100 * Number(box.x0) / page.width_pt}%`;
        button.style.top = `${100 * Number(box.y0) / page.height_pt}%`;
        button.style.width = `${100 * (Number(box.x1) - Number(box.x0)) / page.width_pt}%`;
        button.style.height = `${100 * (Number(box.y1) - Number(box.y0)) / page.height_pt}%`;
        button.addEventListener("click", () => setSelectedMarker(marker.id));
        dom.markerLayer.append(button);
      });
    });
  }

  function analysisBlock(titleText, bodyText, className) {
    if (bodyText === undefined || bodyText === null || String(bodyText).trim() === "") return null;
    const section = create("section", `analysis-block${className ? ` ${className}` : ""}`);
    section.append(create("h3", "", titleText), create("p", "", bodyText));
    return section;
  }
  function appendAnalysisBlocks(blocks) {
    blocks.filter(Boolean).forEach(block => dom.analysisContent.append(block));
  }
  function panelSummary(marker) {
    if (!Array.isArray(marker.panels) || !marker.panels.length) return "";
    return marker.panels.map(panel => `${panel.label || "子图"}：${panel.explanation || panel.summary || ""}`).join("\n\n");
  }
  function sourceBindingLabel(marker) {
    const count = Array.isArray(marker.block_ids) ? marker.block_ids.length : 0;
    if (count) return `已绑定 ${count} 个原文文本块；定位摘录应为对应原文的逐字片段。`;
    if (["figure", "table"].includes(marker.content_type) && marker.visual_candidate_id) {
      return "已绑定原始图表候选与页面裁切；结论仍需结合图注和正文。";
    }
    return "尚无段落级原文绑定；请将本条视为需要定向复核。";
  }
  function appendQuickTakeaway(container, text, marker) {
    if (!text) return;
    const section = create("section", "analysis-takeaway");
    section.append(create("h3", "", "快速结论"), create("p", "", text));
    container.append(section);
  }

  function renderAnalysis() {
    dom.analysisContent.replaceChildren();
    const marker = selectedMarker();
    dom.backToPage.hidden = !marker;
    dom.questionToggle.textContent = marker ? "针对本条注解提问" : "针对本页提问";
    if (marker) {
      const category = categories[marker.category] || categories.context;
      dom.analysisCategory.textContent = typeLabels[marker.content_type] || category.label;
      dom.analysisTitle.textContent = marker.title || "当前原文标注";
      appendQuickTakeaway(dom.analysisContent, marker.takeaway, marker);
      appendAnalysisBlocks([
        analysisBlock("如何阅读", marker.how_to_read),
        analysisBlock("详细解释", marker.explanation),
        analysisBlock("子图说明", panelSummary(marker)),
        analysisBlock("证据支持什么", marker.supports),
        analysisBlock("不能据此推出什么", marker.does_not_support),
        analysisBlock("限定条件与替代解释", marker.limitations || marker.caveats),
        analysisBlock("原文定位", [marker.locator, marker.source_text].filter(Boolean).join("\n\n")),
        analysisBlock("证据状态", claimLabels[marker.claim_status] || claimLabels.unknown),
        analysisBlock("原文绑定", sourceBindingLabel(marker))
      ]);
      if (marker.must_check_source || marker.claim_status !== "direct") {
        appendAnalysisBlocks([
          analysisBlock("必须回到原文", sourceCheckText(marker), "risk-note")
        ]);
      }
      if (["figure", "table", "formula"].includes(marker.content_type) && cropBoxFor(marker)) {
        const button = create("button", "analysis-deep-link", marker.content_type === "formula" ? "进入完整公式精讲" : "进入完整图解");
        button.type = "button";
        button.addEventListener("click", () => setViewMode(marker.content_type === "formula" ? "formulas" : "figures", marker.id));
        dom.analysisContent.append(button);
      }
      appendExperimentalDataAction(dom.analysisContent, {
        marker,
        pageNumber: state.page,
        page: currentPage()
      });
      return;
    }

    dom.analysisCategory.textContent = "本页导读";
    dom.analysisTitle.textContent = `第 ${state.page} 页`;
    const overview = pageNotes().overview || "选择页面中的彩色标注，可以查看对应解释、证据状态和原文位置。";
    appendAnalysisBlocks([analysisBlock("本页阅读目的", overview)]);
    const markers = visibleMarkers();
    if (markers.length) {
      const block = create("section", "analysis-block");
      const figureCount = markers.filter(item => ["figure", "table"].includes(item.content_type)).length;
      block.append(create("h3", "", figureCount ? `本页可展开内容 · 含 ${figureCount} 项图表讲解` : "本页可展开内容"));
      const list = create("div", "marker-list");
      markers.forEach(item => {
        const button = create("button", `marker-list-item ${item.content_type || "text"}`);
        button.type = "button";
        const badge = create("span", "marker-type", typeLabels[item.content_type] || categories[item.category || "context"].label);
        button.append(badge, create("span", "", item.title || "原文标注"));
        button.addEventListener("click", () => setSelectedMarker(item.id));
        list.append(button);
      });
      block.append(list);
      dom.analysisContent.append(block);
    }
  }

  function applyCropAspectClass(canvas, width, height) {
    canvas.classList.remove("crop-tall", "crop-wide", "crop-standard");
    const ratio = width / Math.max(height, 1);
    canvas.classList.add(ratio < 0.9 ? "crop-tall" : ratio > 1.75 ? "crop-wide" : "crop-standard");
  }

  function drawSourceCrop(canvas, page, box) {
    if (!canvas || !page || !box) return;
    const image = new Image();
    image.onload = () => {
      const sx = Number(box.x0) / page.width_pt * image.naturalWidth;
      const sy = Number(box.y0) / page.height_pt * image.naturalHeight;
      const sw = (Number(box.x1) - Number(box.x0)) / page.width_pt * image.naturalWidth;
      const sh = (Number(box.y1) - Number(box.y0)) / page.height_pt * image.naturalHeight;
      canvas.width = Math.max(1, Math.round(sw));
      canvas.height = Math.max(1, Math.round(sh));
      applyCropAspectClass(canvas, sw, sh);
      const context = canvas.getContext("2d");
      context.clearRect(0, 0, canvas.width, canvas.height);
      context.drawImage(image, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
    };
    image.src = page.image;
  }

  function renderAnnotationChips(container) {
    const markers = visibleMarkers();
    if (!markers.length) return;
    const shell = create("section", "bilingual-annotations");
    shell.append(create("h2", "", "本页批注"));
    const chips = create("div", "annotation-chips");
    markers.forEach(marker => {
      const button = create("button", `annotation-chip ${marker.category || "context"}`, marker.title);
      button.type = "button";
      button.addEventListener("click", () => setSelectedMarker(marker.id));
      chips.append(button);
    });
    shell.append(chips);
    container.append(shell);
  }

  function renderVisualCards(container, page) {
    const visualMarkers = visibleMarkers().filter(marker =>
      ["figure", "table", "formula"].includes(marker.content_type) && cropBoxFor(marker)
    );
    if (!visualMarkers.length) return;
    const group = create("section", "visual-cards");
    group.append(create("h2", "", "本页原始图表与公式"));
    visualMarkers.forEach(marker => {
      const card = create("article", "visual-card");
      const button = create("button", "visual-card-title", marker.figure_label || marker.title);
      button.type = "button";
      button.addEventListener("click", () => setSelectedMarker(marker.id));
      const canvas = document.createElement("canvas");
      canvas.setAttribute("aria-label", `${marker.figure_label || marker.title} 原始页面裁切`);
      card.append(button, canvas, create("p", "visual-card-note", "图像与公式保持为原始 PDF 裁切；点击标题查看讲解。"));
      drawSourceCrop(canvas, page, cropBoxFor(marker));
      group.append(card);
    });
    container.append(group);
  }

  function translationRequestText() {
    return `请使用 $paper-reader 为论文《${title}》第 ${state.page} 页生成严谨的逐段中文译文并更新当前阅读器。保留变量、单位、引用号和术语；公式、图表和表格继续使用原始 PDF 裁切。`;
  }

  async function copyTextWithFallback(text, statusNode) {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
        statusNode.textContent = "请求已复制，请粘贴到当前聊天。";
        return;
      }
    } catch (_) {
      // file:// pages commonly reject clipboard permissions; use a visible fallback.
    }
    dom.questionComposer.hidden = false;
    dom.questionInput.value = text;
    autoGrowTextarea();
    dom.questionInput.select();
    statusNode.textContent = "浏览器无法写入剪贴板；完整请求已放入输入框，请手动复制。";
  }

  function renderBilingual() {
    dom.bilingualView.replaceChildren();
    const page = currentPage();
    const translation = pageTranslation();
    const translatedBlocks = translation.blocks || {};
    renderAnnotationChips(dom.bilingualView);

    if (!Object.keys(translatedBlocks).length) {
      const empty = create("section", "translation-empty");
      empty.append(
        create("h2", "", `第 ${state.page} 页暂无双语内容`),
        create("p", "", "这是静态阅读器，不会在页面内伪装实时翻译。可以复制一条带页码的请求，在当前聊天中让 Paper Reader 更新本页。")
      );
      const copyButton = create("button", "secondary-action", "复制翻译本页请求");
      const status = create("p", "muted", "");
      copyButton.type = "button";
      copyButton.addEventListener("click", () => copyTextWithFallback(translationRequestText(), status));
      empty.append(copyButton, status);
      dom.bilingualView.append(empty);
      renderVisualCards(dom.bilingualView, page);
      return;
    }

    page.text_blocks.forEach(block => {
      if (block.kind === "formula_reference" || block.translatable === false) return;
      const shell = create("section", "bilingual-block");
      const anchored = visibleMarkers().filter(marker =>
        Array.isArray(marker.block_ids) && marker.block_ids.includes(block.id)
      );
      if (anchored.length) {
        const badges = create("div", "inline-annotations");
        anchored.forEach(marker => {
          const badge = create("button", `inline-annotation ${marker.category || "context"}`, marker.title);
          badge.type = "button";
          badge.addEventListener("click", () => setSelectedMarker(marker.id));
          badges.append(badge);
        });
        shell.append(badges);
      }
      const isHeading = block.kind === "heading";
      const originalClass = isHeading ? "block-heading" : block.kind === "caption" ? "block-caption" : "block-original";
      shell.append(create(isHeading ? "h3" : "p", originalClass, block.text));
      const translated = translatedBlocks[block.id];
      if (translated) shell.append(create("p", "block-translation", translated));
      else if (!isHeading) shell.append(create("p", "block-translation missing", "本段译文尚未生成。"));
      dom.bilingualView.append(shell);
    });
    renderVisualCards(dom.bilingualView, page);
  }

  function renderTranslationStatus() {
    if (state.languageMode !== "bilingual" || state.viewMode !== "reading") {
      dom.translationStatus.hidden = true;
      return;
    }
    const status = pageTranslation().status;
    dom.translationStatus.hidden = false;
    dom.translationStatus.textContent = status === "complete"
      ? "本页双语覆盖：完整；正式引用仍需核对原始 PDF"
      : status === "partial"
        ? "本页双语覆盖：部分；缺失段落已明确标出"
        : "本页尚无缓存译文；静态阅读器不会自动开始翻译";
  }

  function renderVerificationSummary() {
    dom.verificationSummary.replaceChildren();
    const items = [
      validation.structure === "pass" ? "结构检查：通过" :
        validation.structure === "fail" ? "结构检查：未通过" : "结构检查：待运行",
      validation.source_alignment === "pass" ?
        `原文绑定：通过（${validation.direct_markers_bound || 0}/${validation.direct_markers || 0}）` :
        validation.source_alignment === "fail" ? "原文绑定：不完整" : "原文绑定：待检查",
      "科学判断：不由自动验证器证明"
    ];
    items.forEach(text => dom.verificationSummary.append(create("span", "verification-item", text)));
  }

  function formatDuration(value) {
    if (value === null || value === undefined || value === "") return "未记录";
    const seconds = Number(value);
    if (!Number.isFinite(seconds) || seconds < 0) return "未记录";
    if (seconds < 60) return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)} 秒`;
    const minutes = Math.floor(seconds / 60);
    const remainder = Math.round(seconds % 60);
    return `${minutes} 分 ${remainder} 秒`;
  }

  function renderRunMetrics() {
    dom.runMetrics.replaceChildren();
    dom.runMetricsSummary.textContent = "生成概况";
    const coverage = runInfo.coverage && typeof runInfo.coverage === "object" ? runInfo.coverage : {};
    dom.runMetrics.append(create(
      "p",
      "run-metric-primary",
      `${coverage.pages ?? "—"} 页 · ${coverage.figure_table_markers ?? "—"} 图表 · ${coverage.formula_markers ?? "—"} 公式`
    ));

    const status = create("div", "run-status-list");
    const structurePassed = validation.structure === "pass";
    status.append(create(
      "span",
      `run-status-pill ${structurePassed ? "is-pass" : "is-warning"}`,
      structurePassed ? "结构验证通过" : "结构验证待检查"
    ));
    const warningCount = Number(validation.warning_count);
    if (Number.isFinite(warningCount) && warningCount >= 0) {
      status.append(create(
        "span",
        `run-status-pill ${warningCount ? "is-warning" : "is-pass"}`,
        warningCount ? `需核对 ${warningCount} 项` : "无自动警告"
      ));
    }
    dom.runMetrics.append(status);

    const timings = runInfo.timings_seconds && typeof runInfo.timings_seconds === "object"
      ? runInfo.timings_seconds : {};
    const phases = [
      ["PDF 解析与渲染", timings.pdf_parse_and_render],
      ["上下文索引", timings.context_indexing],
      ["内容分析", timings.content_analysis],
      ["阅读器构建", timings.packaging],
      ["结构验证", timings.validation]
    ];
    const recorded = phases.filter(([, value]) => value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value)) && Number(value) >= 0);
    if (recorded.length === phases.length) {
      const row = create("div", "run-metric-row");
      row.append(
        create("span", "", "总耗时"),
        create("strong", "", formatDuration(recorded.reduce((sum, [, value]) => sum + Number(value), 0)))
      );
      dom.runMetrics.append(row);
    }
  }

  function sourcePdfHref(pageNumber) {
    return `${data.paper.source_pdf || "assets/source.pdf"}#page=${pageNumber}`;
  }

  function updateSourcePdfLink(pageNumber = state.page) {
    dom.sourcePdfLink.href = sourcePdfHref(pageNumber);
    dom.sourcePdfLink.textContent = `打开原始 PDF（第 ${pageNumber} 页）`;
  }

  function renderPage() {
    const page = currentPage();
    dom.pageStatus.textContent = `第 ${state.page} / ${pages.length} 页`;
    updateSourcePdfLink(state.page);
    dom.pageSelect.value = String(state.page);
    dom.previousPage.disabled = state.page === 1;
    dom.nextPage.disabled = state.page === pages.length;
    dom.pageImage.src = page.image;
    dom.pageImage.alt = `${title} 第 ${state.page} 页`;
    dom.pageCanvas.style.setProperty("--page-width", `${state.zoom}%`);
    renderSections();
    renderMarkers();
    renderAnalysis();
    renderTranslationStatus();
    if (state.languageMode === "bilingual") renderBilingual();
  }

  function stringList(value) {
    if (!value) return [];
    if (Array.isArray(value)) return value.map(item => typeof item === "string" ? item : item.text || item.explanation || item.value || "").filter(Boolean);
    return [String(value)];
  }
  function sourceCheckText(marker) {
    const items = stringList(marker.source_checks).map(item => typeof item === "string" ? item : String(item));
    if (items.length) return items.join("\n");
    return "引用、公式细节或关键判断请结合完整上下文核对。";
  }
  function experimentalOriginLabel(origin) {
    return {
      author_generated: "本文作者产生",
      reused_external: "复用外部实验数据",
      mixed: "本文实验与外部实验数据混合",
      uncertain: "来源尚待核对"
    }[origin] || "来源尚待核对";
  }
  function experimentalDataContext(marker) {
    const info = experimentalDataInfo(marker);
    if (!info) return [];
    const lines = [
      `实验数据线索状态：${info.status === "present" ? "论文已明确使用实验测量" : "存在具体线索但尚未确认"}`,
      `实验数据来源类型：${experimentalOriginLabel(info.origin)}`,
      info.role ? `实验数据在本项中的作用：${info.role}` : ""
    ];
    const hints = stringList(info.source_hints || info.source_hint);
    if (hints.length) lines.push(`论文内来源线索：${hints.join("；")}`);
    const identifiers = stringList(info.reported_identifiers);
    if (identifiers.length) lines.push(`论文报告的标识符：${identifiers.join("；")}`);
    return lines.filter(Boolean);
  }
  function experimentalDataPrompt() {
    return "请追踪支撑当前图表、方法或结论的实验数据来源。只计入由生物、物理、临床或仪器实验产生的原始或处理后测量数据；排除模拟结果、理论计算、模型输出、代码和纯文献参数。请先核对主文、图注、Methods、Data availability 和已提供补充材料，再仅沿明确线索核对数据仓库或来源论文。若当前项目实际没有实验数据，请明确说明并停止，不要用其他资源补位。请分别标明：论文声称、链接已核验、文件已下载、数据已分析。";
  }
  function openExperimentalDataComposer(markerRef) {
    if (!markerRef || !experimentalDataInfo(markerRef.marker)) return;
    openQuestionComposer({ markerRef, intent: "experimental-data-source" }, experimentalDataPrompt());
  }
  function appendExperimentalDataAction(container, markerRef) {
    const info = markerRef && experimentalDataInfo(markerRef.marker);
    if (!info) return;
    const shell = create("section", "experimental-data-callout");
    const button = create("button", "experimental-data-action", "查实验数据来源");
    button.type = "button";
    button.addEventListener("click", () => openExperimentalDataComposer(markerRef));
    const note = info.status === "present"
      ? "只追踪支撑本项的实验测量数据；模拟、模型和代码不会被列入。"
      : "这里存在具体实验数据线索，但来源尚未确认；点击后可定向核对。";
    shell.append(button, create("p", "", note));
    container.append(shell);
  }
  function sectionText(node) {
    return node ? node.innerText.replace(/\n{3,}/g, "\n\n").trim() : "";
  }
  function slug(value, index) {
    const cleaned = String(value || "section").toLowerCase().replace(/[^a-z0-9\u4e00-\u9fff]+/g, "-").replace(/^-|-$/g, "");
    return `teaching-${index + 1}-${cleaned || "section"}`;
  }

  function createTextBody(value, ordered = false) {
    const items = stringList(value);
    if (!items.length) return null;
    if (items.length === 1 && !Array.isArray(value)) return create("p", "", items[0]);
    const list = create(ordered ? "ol" : "ul", "");
    items.forEach(item => list.append(create("li", "", item)));
    return list;
  }

  function createPanelsBody(panels) {
    if (!Array.isArray(panels) || !panels.length) return null;
    const grid = create("div", "teaching-grid");
    panels.forEach(panel => {
      const box = create("article", "teaching-box");
      box.append(create("h3", "", panel.label || "子图"), create("p", "", panel.explanation || panel.summary || ""));
      grid.append(box);
    });
    return grid;
  }

  function createEvidenceBoundary(marker) {
    if (!marker.supports && !marker.does_not_support) return null;
    const grid = create("div", "teaching-grid");
    if (marker.supports) {
      const support = create("article", "teaching-box supports");
      support.append(create("h3", "", "这项证据支持什么"), create("p", "", marker.supports));
      grid.append(support);
    }
    if (marker.does_not_support) {
      const limit = create("article", "teaching-box limits");
      limit.append(create("h3", "", "不能据此推出什么"), create("p", "", marker.does_not_support));
      grid.append(limit);
    }
    return grid;
  }

  function createSymbolTable(symbols) {
    if (!Array.isArray(symbols) || !symbols.length) return null;
    const table = create("table", "symbol-table");
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    ["符号", "含义", "单位或范围", "来源/备注"].forEach(label => headRow.append(create("th", "", label)));
    head.append(headRow);
    const body = document.createElement("tbody");
    symbols.forEach(symbol => {
      const row = document.createElement("tr");
      row.append(
        create("td", "", symbol.symbol || "—"),
        create("td", "", symbol.meaning || symbol.definition || "—"),
        create("td", "", symbol.unit || symbol.range || "原文未报告"),
        create("td", "", symbol.source || symbol.note || "—")
      );
      body.append(row);
    });
    table.append(head, body);
    return table;
  }

  function createKeyValueBody(values) {
    if (!Array.isArray(values) || !values.length) return null;
    const grid = create("div", "teaching-grid");
    values.forEach(value => {
      const box = create("article", "teaching-box");
      box.append(
        create("h3", "", value.label || value.name || "关键观察"),
        create("p", "", [value.value, value.meaning || value.explanation].filter(Boolean).join("："))
      );
      grid.append(box);
    });
    return grid;
  }

  function referencedPageNumbers(marker, currentPageNumber) {
    const text = [marker.locator, marker.source_text, ...stringList(marker.source_checks)].filter(Boolean).join(" ");
    const found = new Set([Number(currentPageNumber)]);
    const patterns = [/(?:\bp(?:age)?\.?\s*)(\d{1,4})\b/gi, /第\s*(\d{1,4})\s*页/g];
    patterns.forEach(pattern => {
      let match;
      while ((match = pattern.exec(text)) !== null) {
        const pageNumber = Number(match[1]);
        if (Number.isInteger(pageNumber) && pageNumber >= 1 && pageNumber <= pages.length) found.add(pageNumber);
      }
    });
    return Array.from(found).sort((a, b) => a - b);
  }

  function openReadingAt(pageNumber, markerId = null) {
    const targetPage = Math.max(1, Math.min(pages.length, Number(pageNumber) || 1));
    const targetMarkers = notesForPage(targetPage).markers || [];
    state.page = targetPage;
    state.selectedMarker = targetMarkers.some(marker => marker.id === markerId) ? markerId : null;
    setMode("original");
    setViewMode("reading");
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const markerNode = state.selectedMarker
        ? Array.from(dom.markerLayer.querySelectorAll(".marker-box")).find(node => node.dataset.markerId === state.selectedMarker)
        : null;
      (markerNode || dom.pageCanvas).scrollIntoView({ behavior: "auto", block: markerNode ? "center" : "start" });
    }));
  }

  function createSourceBody(marker, markerRef) {
    const shell = create("div", "source-check-list");
    const actions = create("div", "source-actions");
    const locate = create("button", "source-action primary-source-action", `定位本项原文 · p.${markerRef.pageNumber}`);
    locate.type = "button";
    locate.addEventListener("click", () => openReadingAt(markerRef.pageNumber, marker.id));
    actions.append(locate);
    referencedPageNumbers(marker, markerRef.pageNumber)
      .filter(pageNumber => pageNumber !== markerRef.pageNumber)
      .forEach(pageNumber => {
        const button = create("button", "source-action", `查看 p.${pageNumber} 上下文`);
        button.type = "button";
        button.addEventListener("click", () => openReadingAt(pageNumber));
        actions.append(button);
      });
    const pdfLink = create("a", "source-action source-action-link", `在原始 PDF 打开 p.${markerRef.pageNumber}`);
    pdfLink.href = sourcePdfHref(markerRef.pageNumber);
    pdfLink.target = "_blank";
    pdfLink.rel = "noopener";
    actions.append(pdfLink);
    const lines = [
      marker.locator ? `原文位置：${marker.locator}` : "",
      marker.source_text ? `定位摘录：${marker.source_text}` : "",
      `证据状态：${claimLabels[marker.claim_status] || claimLabels.unknown}`,
      `原文绑定：${sourceBindingLabel(marker)}`
    ].filter(Boolean);
    const checks = stringList(marker.source_checks);
    const list = create("ul", "");
    lines.concat(checks.length ? checks.map(item => `需核对：${item}`) : []).forEach(item => list.append(create("li", "", item)));
    shell.append(actions, list);
    return shell;
  }

  function addTeachingSection(collection, titleText, body, markerRef) {
    if (!body) return;
    const index = collection.length;
    const section = create("section", "teaching-section");
    section.id = slug(titleText, index);
    const heading = create("div", "teaching-section-heading");
    heading.append(create("h2", "", titleText));
    const ask = create("button", "question-action", "针对这个点提问");
    ask.type = "button";
    heading.append(ask);
    section.append(heading, body);
    ask.addEventListener("click", () => openQuestionComposer({
      markerRef,
      point: { title: titleText, explanation: sectionText(body) }
    }));
    collection.push({ title: titleText, section });
  }

  function buildTeachingSections(markerRef) {
    const marker = markerRef.marker;
    const sections = [];
    addTeachingSection(sections, "读前背景", createTextBody(marker.prerequisites || marker.background), markerRef);
    addTeachingSection(sections, marker.content_type === "formula" ? "如何读取这条公式" : "建议的阅读顺序", createTextBody(marker.reading_steps || marker.how_to_read, true), markerRef);
    addTeachingSection(sections, "详细解释", createTextBody(marker.explanation), markerRef);
    addTeachingSection(sections, "逐面板解析", createPanelsBody(marker.panels), markerRef);
    addTeachingSection(sections, "关键观察与数值", createKeyValueBody(marker.key_values || marker.key_observations), markerRef);
    addTeachingSection(sections, "符号表", createSymbolTable(marker.symbols), markerRef);
    addTeachingSection(sections, "推导与使用步骤", createTextBody(marker.derivation_steps || marker.use_steps, true), markerRef);

    if (Array.isArray(marker.detail_sections)) {
      marker.detail_sections.forEach(detail => {
        if (!detail || !detail.title) return;
        const body = createTextBody(detail.items || detail.body || detail.explanation, Boolean(detail.ordered));
        addTeachingSection(sections, detail.title, body, markerRef);
      });
    }

    addTeachingSection(sections, "证据边界", createEvidenceBoundary(marker), markerRef);
    addTeachingSection(sections, "限定条件、常见误读与替代解释", createTextBody([
      ...stringList(marker.limitations || marker.caveats),
      ...stringList(marker.common_misreadings)
    ]), markerRef);
    addTeachingSection(sections, "回原文核对", createSourceBody(marker, markerRef), markerRef);
    return sections;
  }

  function renderExplainerNavigation(items) {
    dom.explainerNavigation.replaceChildren();
    items.forEach((ref, index) => {
      const button = create("button", "explainer-thumb");
      button.type = "button";
      button.classList.toggle("active", ref.marker.id === state.explainerMarker);
      const visual = create("span", "explainer-thumb-visual");
      const canvas = document.createElement("canvas");
      canvas.setAttribute("aria-label", `${ref.marker.title} 预览`);
      visual.append(canvas);
      const label = create("span", "explainer-thumb-label");
      label.append(
        create("span", "", `${index + 1}. ${ref.marker.figure_label || ref.marker.title}`),
        create("small", "", `p.${ref.pageNumber} · ${typeLabels[ref.marker.content_type] || "讲解"}`)
      );
      button.append(visual, label);
      button.addEventListener("click", () => {
        state.explainerMarker = ref.marker.id;
        renderExplainer();
        updateHash();
        window.scrollTo({ top: 0, behavior: "smooth" });
      });
      dom.explainerNavigation.append(button);
      drawSourceCrop(canvas, ref.page, cropBoxFor(ref.marker));
    });
  }

  function renderExplainer() {
    const items = explainerItems();
    if (!items.length) {
      dom.pageStatus.textContent = state.viewMode === "figures" ? "未发现已讲解图表" : "未发现已讲解公式";
      dom.explainerNavigation.replaceChildren();
      dom.explainerTitle.textContent = state.viewMode === "figures" ? "暂无图表讲解" : "暂无公式精讲";
      dom.explainerContent.replaceChildren(create("p", "muted", "当前 notes 中没有同时具备来源裁切和讲解的项目。"));
      dom.explainerTakeaway.replaceChildren();
      dom.explainerSourceFrame.hidden = true;
      dom.experimentalDataAction.hidden = true;
      return;
    }
    let ref = activeExplainerRef();
    if (!ref) ref = items[0];
    state.explainerMarker = ref.marker.id;
    const marker = ref.marker;
    const currentIndex = items.findIndex(item => item.marker.id === marker.id);
    dom.explainerSourceFrame.hidden = false;
    dom.pageStatus.textContent = `${state.viewMode === "figures" ? "图表" : "公式"} ${currentIndex + 1} / ${items.length} · 第 ${ref.pageNumber} 页`;
    dom.explainerCategory.textContent = typeLabels[marker.content_type] || "详细讲解";
    dom.explainerTitle.textContent = marker.title || "当前讲解";
    dom.explainerLocator.textContent = marker.locator || `p.${ref.pageNumber}`;
    dom.questionWhole.textContent = marker.content_type === "formula" ? "针对本公式提问" : "针对本图提问";
    dom.experimentalDataAction.hidden = !experimentalDataInfo(marker);
    updateSourcePdfLink(ref.pageNumber);
    renderExplainerNavigation(items);
    drawSourceCrop(dom.explainerSourceCanvas, ref.page, cropBoxFor(marker));

    dom.explainerTakeaway.replaceChildren(
      create("strong", "", "快速结论"),
      create("p", "", marker.takeaway || "请结合下方讲解与原始裁切阅读。")
    );
    dom.explainerContent.replaceChildren();
    dom.explainerSectionNav.replaceChildren();
    const sections = buildTeachingSections(ref);
    sections.forEach(item => {
      dom.explainerContent.append(item.section);
      const navButton = create("button", "", item.title);
      navButton.type = "button";
      navButton.addEventListener("click", () => item.section.scrollIntoView({ behavior: "smooth", block: "start" }));
      dom.explainerSectionNav.append(navButton);
    });
  }

  function questionContextText(target = state.questionTarget) {
    if (!target || !target.markerRef) return `将附带：论文 · 第 ${state.page} 页 · 本页导读`;
    const ref = target.markerRef;
    const label = ref.marker.figure_label || ref.marker.title;
    const point = target.point ? ` · ${target.point.title}` : "";
    const intent = target.intent === "experimental-data-source" ? " · 实验数据来源" : "";
    return `将附带：论文 · 第 ${ref.pageNumber} 页 · ${label}${point}${intent}`;
  }

  function defaultQuestionTarget() {
    const marker = selectedMarker();
    if (marker) return { markerRef: { marker, pageNumber: state.page, page: currentPage() } };
    return null;
  }

  function openQuestionComposer(target, initialText = "") {
    state.questionTarget = target || defaultQuestionTarget();
    dom.questionComposer.hidden = false;
    dom.questionContext.textContent = questionContextText();
    dom.questionStatus.textContent = "";
    dom.questionInput.value = initialText;
    autoGrowTextarea();
    dom.questionInput.focus();
  }
  function closeQuestionComposer() {
    dom.questionComposer.hidden = true;
    dom.questionStatus.textContent = "";
    state.questionTarget = null;
  }
  function autoGrowTextarea() {
    dom.questionInput.style.height = "auto";
    dom.questionInput.style.height = `${Math.min(360, Math.max(94, dom.questionInput.scrollHeight))}px`;
  }

  function preparedQuestion(userQuestion) {
    const target = state.questionTarget;
    if (!target || !target.markerRef) {
      return `${userQuestion}\n\n阅读上下文：\n论文：《${title}》\n当前页：第 ${state.page} 页\n范围：本页导读\n\n请区分原文直接证据、有限推断和未知；涉及引用、公式或关键结论时提醒我核对原始 PDF。`;
    }
    const ref = target.markerRef;
    const marker = ref.marker;
    const blockText = markerBlocks(marker, ref.pageNumber).map(block => block.text).join("\n\n");
    const currentExplanation = target.point?.explanation || [marker.takeaway, marker.explanation].filter(Boolean).join("\n\n");
    const context = [
      `论文：《${title}》`,
      `当前页：第 ${ref.pageNumber} 页`,
      `标注 ID：${marker.id}`,
      `标注：${marker.title}`,
      marker.figure_label ? `图表/公式：${marker.figure_label}` : "",
      target.point ? `当前讲解点：${target.point.title}` : "",
      marker.locator ? `原文定位：${marker.locator}` : "",
      `证据状态：${claimLabels[marker.claim_status] || claimLabels.unknown}`,
      marker.source_text ? `定位摘录：${marker.source_text}` : "",
      blockText ? `相关原文块：${blockText}` : "",
      currentExplanation ? `当前解释：${currentExplanation}` : "",
      ...experimentalDataContext(marker)
    ].filter(Boolean).join("\n");
    const instruction = target.intent === "experimental-data-source"
      ? "请只追踪支撑当前项目的实验测量数据，不要把模拟、理论计算、模型输出、代码或纯文献参数列为实验数据。若没有实验数据，明确说明并停止。区分论文声称、链接已核验、文件已下载和数据已分析；不要把尚未访问的来源写成已经核验。"
      : "请直接回答当前问题，并区分原文直接证据、代数或逻辑推导、有限推断和未知；不要脱离所附上下文重新猜测。涉及引用、公式或关键结论时说明具体需要核对的原文位置。";
    return `${userQuestion}\n\n阅读上下文：\n${context}\n\n${instruction}`;
  }

  async function sendQuestion() {
    const userQuestion = dom.questionInput.value.trim();
    if (!userQuestion) {
      dom.questionStatus.textContent = "请先输入问题。";
      return;
    }
    const message = preparedQuestion(userQuestion);
    try {
      if (window.openai && typeof window.openai.sendFollowUpMessage === "function") {
        await window.openai.sendFollowUpMessage({ prompt: message, title: "针对论文当前内容提问" });
        dom.questionStatus.textContent = "已作为当前任务的新消息发送。";
        return;
      }
      await copyTextWithFallback(message, dom.questionStatus);
    } catch (error) {
      dom.questionInput.value = message;
      autoGrowTextarea();
      dom.questionInput.select();
      dom.questionStatus.textContent = `未能自动发送；完整问题已放回输入框。${error && error.message ? ` ${error.message}` : ""}`;
    }
  }

  function openLargeCrop() {
    const ref = activeExplainerRef();
    if (!ref) return;
    drawSourceCrop(dom.cropDialogCanvas, ref.page, cropBoxFor(ref.marker));
    if (typeof dom.cropDialog.showModal === "function") dom.cropDialog.showModal();
    else dom.cropDialog.setAttribute("open", "");
  }
  function closeLargeCrop() {
    if (typeof dom.cropDialog.close === "function") dom.cropDialog.close();
    else dom.cropDialog.removeAttribute("open");
  }

  function openExplainerItemInReading() {
    const ref = activeExplainerRef();
    if (!ref) return;
    openReadingAt(ref.pageNumber, ref.marker.id);
  }

  function initialize() {
    document.title = `${title} · Paper Reader`;
    dom.paperTitle.textContent = title;
    pages.forEach(page => {
      const option = create("option", "", `第 ${page.number} 页`);
      option.value = String(page.number);
      dom.pageSelect.append(option);
    });
    renderFilters();
    renderVerificationSummary();
    renderRunMetrics();
    dom.readingViewMode.addEventListener("click", () => setViewMode("reading"));
    dom.figureViewMode.addEventListener("click", () => setViewMode("figures"));
    dom.formulaViewMode.addEventListener("click", () => setViewMode("formulas"));
    dom.originalMode.addEventListener("click", () => setMode("original"));
    dom.bilingualMode.addEventListener("click", () => setMode("bilingual"));
    dom.previousPage.addEventListener("click", () => setPage(state.page - 1));
    dom.nextPage.addEventListener("click", () => setPage(state.page + 1));
    dom.pageSelect.addEventListener("change", event => setPage(event.target.value));
    dom.zoomSelect.addEventListener("change", event => {
      state.zoom = Number(event.target.value) || 100;
      dom.pageCanvas.style.setProperty("--page-width", `${state.zoom}%`);
    });
    dom.markerMasterToggle.addEventListener("click", toggleAllMarkers);
    dom.backToPage.addEventListener("click", clearMarkerSelection);
    dom.questionToggle.addEventListener("click", () => openQuestionComposer());
    dom.questionWhole.addEventListener("click", () => openQuestionComposer({ markerRef: activeExplainerRef() }));
    dom.experimentalDataAction.addEventListener("click", () => openExperimentalDataComposer(activeExplainerRef()));
    dom.openInReading.addEventListener("click", openExplainerItemInReading);
    dom.openCropLarge.addEventListener("click", openLargeCrop);
    dom.closeCropDialog.addEventListener("click", closeLargeCrop);
    dom.cancelQuestion.addEventListener("click", closeQuestionComposer);
    dom.questionInput.addEventListener("input", autoGrowTextarea);
    dom.askButton.addEventListener("click", sendQuestion);
    dom.questionComposer.addEventListener("click", event => {
      if (event.target === dom.questionComposer) closeQuestionComposer();
    });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape") {
        if (dom.cropDialog.open) closeLargeCrop();
        else if (!dom.questionComposer.hidden) closeQuestionComposer();
        else if (state.viewMode === "reading" && state.selectedMarker) clearMarkerSelection();
        return;
      }
      if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) return;
      if (state.viewMode === "reading") {
        if (event.key === "ArrowLeft") setPage(state.page - 1);
        if (event.key === "ArrowRight") setPage(state.page + 1);
      }
    });
    setMode(state.languageMode);
    setViewMode(state.viewMode, state.explainerMarker);
  }

  initialize();
})();
