document_id_selected = ""; // global selector state

document.addEventListener("DOMContentLoaded", () => {
    // State variables
    let activeDocId = "";
    let activeDocPages = 0;
    let documents = [];
    let isUploading = false;

    // DOM Elements
    const apiKeyToggleBtn = document.getElementById("api-key-toggle-btn");
    const apiKeyModal = document.getElementById("api-key-modal");
    const apiKeyInput = document.getElementById("api-key-input");
    const apiKeySaveBtn = document.getElementById("api-key-save-btn");
    const keyStatusDot = document.querySelector(".key-status-dot");

    const dropZone = document.getElementById("drop-zone");
    const fileInput = document.getElementById("file-input");
    const uploadProgress = document.getElementById("upload-progress");
    const progressFill = uploadProgress.querySelector(".progress-fill");
    const progressText = uploadProgress.querySelector(".progress-text");

    const documentsList = document.getElementById("documents-list");
    const filterAllBtn = document.getElementById("filter-all-btn");
    const activeDocIndicator = document.getElementById("active-doc-indicator");

    const chatMessages = document.getElementById("chat-messages");
    const chatForm = document.getElementById("chat-form");
    const chatInput = document.getElementById("chat-input");
    const dynamicSuggestions = document.getElementById("dynamic-suggestions");

    const tabButtons = document.querySelectorAll(".tab-btn");
    const tabContents = document.querySelectorAll(".tab-content");

    const sourcesListContainer = document.getElementById("sources-list-container");
    const retrievedSourcesTab = document.getElementById("retrieved-sources");
    const emptySourcesState = retrievedSourcesTab.querySelector(".empty-inspector-state");

    const visualViewerTab = document.getElementById("visual-viewer");
    const emptyVisualState = visualViewerTab.querySelector(".empty-inspector-state");
    const visualViewportContainer = document.getElementById("visual-viewport-container");
    const inspectedImage = document.getElementById("inspected-image");
    const viewportDescription = document.getElementById("viewport-description");
    const zoomResetBtn = document.getElementById("zoom-reset");

    const pageBrowserTab = document.getElementById("page-browser");
    const pageBrowserEmptyState = document.getElementById("page-browser-empty-state");
    const pageGridContainer = document.getElementById("page-grid-container");

    const toast = document.getElementById("toast");

    // Initialize Page
    checkApiConfig();
    fetchDocuments();

    // ----------------------------------------------------
    // API KEY MANAGEMENT
    // ----------------------------------------------------
    apiKeyToggleBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        apiKeyModal.classList.toggle("hidden");
    });

    document.addEventListener("click", (e) => {
        if (!apiKeyModal.contains(e.target) && e.target !== apiKeyToggleBtn) {
            apiKeyModal.classList.add("hidden");
        }
    });

    apiKeySaveBtn.addEventListener("click", async () => {
        const key = apiKeyInput.value.trim();
        if (!key) {
            showToast("API Key cannot be empty", "error");
            return;
        }

        try {
            apiKeySaveBtn.disabled = true;
            apiKeySaveBtn.textContent = "Saving...";
            
            const response = await fetch("/api/config", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ api_key: key })
            });

            const result = await response.json();
            if (response.ok) {
                showToast("Gemini API key configured successfully", "success");
                apiKeyModal.classList.add("hidden");
                apiKeyInput.value = "";
                checkApiConfig();
            } else {
                showToast(result.detail || "Failed to update configuration", "error");
            }
        } catch (error) {
            showToast("Network error configuring API key", "error");
        } finally {
            apiKeySaveBtn.disabled = false;
            apiKeySaveBtn.textContent = "Save Key";
        }
    });

    async function checkApiConfig() {
        try {
            const response = await fetch("/api/config");
            const data = await response.json();
            if (data.has_api_key) {
                keyStatusDot.className = "key-status-dot configured";
                apiKeyToggleBtn.querySelector(".btn-text").textContent = "API Configured";
            } else {
                keyStatusDot.className = "key-status-dot unconfigured";
                apiKeyToggleBtn.querySelector(".btn-text").textContent = "Setup API Key";
            }
        } catch (error) {
            console.error("Error checking API configuration:", error);
        }
    }

    // ----------------------------------------------------
    // DOCUMENT MANAGEMENT
    // ----------------------------------------------------
    dropZone.addEventListener("click", () => {
        if (!isUploading) {
            fileInput.click();
        }
    });

    fileInput.addEventListener("change", (e) => {
        const file = e.target.files[0];
        if (file) handleFileUpload(file);
    });

    dropZone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropZone.style.borderColor = "var(--color-cyan)";
        dropZone.style.background = "rgba(6, 182, 212, 0.05)";
    });

    dropZone.addEventListener("dragleave", () => {
        dropZone.style.borderColor = "rgba(99, 102, 241, 0.3)";
        dropZone.style.background = "rgba(99, 102, 241, 0.03)";
    });

    dropZone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropZone.style.borderColor = "rgba(99, 102, 241, 0.3)";
        dropZone.style.background = "rgba(99, 102, 241, 0.03)";
        
        if (isUploading) return;
        const file = e.dataTransfer.files[0];
        if (file) handleFileUpload(file);
    });

    async function handleFileUpload(file) {
        if (!file.name.endsWith(".pdf")) {
            showToast("Only PDF files are supported", "error");
            return;
        }

        isUploading = true;
        uploadProgress.classList.remove("hidden");
        progressFill.style.width = "10%";
        progressText.textContent = "Uploading PDF...";

        const formData = new FormData();
        formData.append("file", file);

        try {
            // Processing updates
            const progressInterval = setInterval(() => {
                let currentWidth = parseFloat(progressFill.style.width);
                if (currentWidth < 90) {
                    let increment = currentWidth < 50 ? 8 : 3;
                    progressFill.style.width = `${currentWidth + increment}%`;
                    if (currentWidth > 60) {
                        progressText.textContent = "Extracting visual charts & embedding chunks...";
                    } else if (currentWidth > 35) {
                        progressText.textContent = "Segmenting text in parallel...";
                    }
                }
            }, 500);

            const response = await fetch("/api/upload", {
                method: "POST",
                body: formData
            });

            clearInterval(progressInterval);

            const result = await response.json();
            if (response.ok) {
                progressFill.style.width = "100%";
                progressText.textContent = "Done!";
                showToast(`Successfully processed: ${file.name}`, "success");
                
                activeDocId = result.document_id;
                document_id_selected = activeDocId;
                
                await fetchDocuments();
            } else {
                showToast(result.detail || "Failed to process PDF", "error");
            }
        } catch (error) {
            showToast("Error uploading file to server", "error");
        } finally {
            setTimeout(() => {
                uploadProgress.classList.add("hidden");
                progressFill.style.width = "0%";
                isUploading = false;
                fileInput.value = "";
            }, 1000);
        }
    }

    async function fetchDocuments() {
        try {
            const response = await fetch("/api/documents");
            documents = await response.json();
            renderDocumentsList();
        } catch (error) {
            console.error("Error fetching documents:", error);
            showToast("Could not load documents list", "error");
        }
    }

    function renderDocumentsList() {
        documentsList.innerHTML = "";
        
        if (documents.length === 0) {
            documentsList.innerHTML = `<div class="empty-state">No documents uploaded yet.</div>`;
            return;
        }

        documents.forEach(doc => {
            const isSelected = doc.id === activeDocId;
            const docItem = document.createElement("div");
            docItem.className = `doc-item ${isSelected ? "selected" : ""}`;
            docItem.dataset.id = doc.id;
            
            docItem.innerHTML = `
                <div class="doc-info">
                    <div class="doc-icon">PDF</div>
                    <div class="doc-name" title="${doc.filename}">${doc.filename}</div>
                </div>
                <button class="delete-doc-btn" title="Delete Document">&times;</button>
            `;

            docItem.addEventListener("click", (e) => {
                if (e.target.classList.contains("delete-doc-btn")) {
                    e.stopPropagation();
                    deleteDocument(doc.id);
                    return;
                }
                selectDocument(doc.id, doc.filename, doc.pages);
            });

            documentsList.appendChild(docItem);
        });

        if (activeDocId) {
            const currentDoc = documents.find(d => d.id === activeDocId);
            if (currentDoc) {
                selectDocument(activeDocId, currentDoc.filename, currentDoc.pages);
            } else {
                selectDocument("", "", 0);
            }
        } else {
            selectDocument("", "", 0);
        }
    }

    function selectDocument(id, filename, pages) {
        activeDocId = id;
        document_id_selected = id;
        activeDocPages = pages || 0;

        filterAllBtn.classList.toggle("active", !id);
        
        const docItems = documentsList.querySelectorAll(".doc-item");
        docItems.forEach(item => {
            item.classList.toggle("selected", item.dataset.id === id);
        });

        if (id) {
            activeDocIndicator.textContent = filename;
            activeDocIndicator.className = "active-doc-badge";
            activeDocIndicator.style.background = "rgba(99, 102, 241, 0.1)";
            activeDocIndicator.style.borderColor = "rgba(99, 102, 241, 0.2)";
            activeDocIndicator.style.color = "var(--color-primary)";

            // Update Page Browser Tab
            pageBrowserEmptyState.classList.add("hidden");
            pageGridContainer.classList.remove("hidden");
            renderPageGrid(id, filename, activeDocPages);

            // Fetch dynamic suggested questions
            fetchSuggestions(id);
        } else {
            activeDocIndicator.textContent = "All Files Selected";
            activeDocIndicator.className = "active-doc-badge";
            activeDocIndicator.style.background = "rgba(6, 182, 212, 0.1)";
            activeDocIndicator.style.borderColor = "rgba(6, 182, 212, 0.2)";
            activeDocIndicator.style.color = "var(--color-cyan)";

            // Reset Page Browser Tab
            pageGridContainer.classList.add("hidden");
            pageBrowserEmptyState.classList.remove("hidden");
            pageGridContainer.innerHTML = "";

            // Reset dynamic suggestions
            dynamicSuggestions.classList.add("hidden");
            dynamicSuggestions.innerHTML = "";
        }
    }

    filterAllBtn.addEventListener("click", () => selectDocument("", "", 0));

    async function deleteDocument(id) {
        if (!confirm("Are you sure you want to delete this document? All parsed pages and chart indexings will be permanently removed.")) {
            return;
        }

        try {
            const response = await fetch(`/api/documents/${id}`, {
                method: "DELETE"
            });
            if (response.ok) {
                showToast("Document deleted successfully", "success");
                if (activeDocId === id) {
                    activeDocId = "";
                    document_id_selected = "";
                }
                await fetchDocuments();
            } else {
                showToast("Failed to delete document", "error");
            }
        } catch (error) {
            showToast("Network error deleting document", "error");
        }
    }

    // ----------------------------------------------------
    // DYNAMIC SUGGESTIONS
    // ----------------------------------------------------
    async function fetchSuggestions(docId) {
        if (!docId) {
            dynamicSuggestions.classList.add("hidden");
            dynamicSuggestions.innerHTML = "";
            return;
        }
        
        try {
            dynamicSuggestions.classList.add("hidden");
            const response = await fetch(`/api/documents/${docId}/suggested-questions`);
            if (!response.ok) return;
            const data = await response.json();
            
            if (data.questions && data.questions.length > 0) {
                dynamicSuggestions.innerHTML = "";
                data.questions.forEach(q => {
                    const chip = document.createElement("button");
                    chip.className = "suggestion-chip";
                    chip.textContent = q;
                    chip.title = q;
                    chip.addEventListener("click", () => {
                        chatInput.value = q;
                        chatForm.dispatchEvent(new Event("submit"));
                    });
                    dynamicSuggestions.appendChild(chip);
                });
                dynamicSuggestions.classList.remove("hidden");
            }
        } catch (error) {
            console.error("Error fetching suggestions:", error);
        }
    }

    // ----------------------------------------------------
    // PAGE BROWSER
    // ----------------------------------------------------
    function renderPageGrid(docId, filename, pages) {
        pageGridContainer.innerHTML = "";
        if (pages === 0) {
            pageGridContainer.innerHTML = `<div class="empty-state">No pages extracted yet.</div>`;
            return;
        }

        for (let p = 1; p <= pages; p++) {
            const card = document.createElement("div");
            card.className = "page-card";
            card.innerHTML = `
                <div class="page-card-num">#${p}</div>
                <div class="page-card-label">Page ${p}</div>
            `;
            card.addEventListener("click", () => {
                showPageOnDemand(docId, p, filename);
            });
            pageGridContainer.appendChild(card);
        }
    }

    function showPageOnDemand(docId, pageNum, filename) {
        const computedPath = `/data/extracted_images/${docId}/page_${pageNum}.png`;
        inspectImage(computedPath, `Page ${pageNum} Content of document "${filename}"`);
    }

    // ----------------------------------------------------
    // CHAT & RAG
    // ----------------------------------------------------
    chatForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const queryText = chatInput.value.trim();
        if (!queryText) return;

        chatInput.value = "";
        appendMessage(queryText, "user");

        const loaderId = appendLoaderMessage();

        try {
            const response = await fetch("/api/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    query: queryText,
                    document_id: activeDocId || null,
                    top_k: 5
                })
            });

            const result = await response.json();
            removeLoaderMessage(loaderId);

            if (response.ok) {
                appendMessage(result.answer, "assistant");
                renderRetrievedSources(result.sources);
            } else {
                appendMessage(`Error: ${result.detail || "Failed to retrieve an answer"}`, "assistant");
            }
        } catch (error) {
            removeLoaderMessage(loaderId);
            appendMessage("Failed to connect to backend server. Please verify FastAPI is running.", "assistant");
        }
    });

    document.addEventListener("click", (e) => {
        if (e.target.tagName === "LI" && e.target.parentElement.classList.contains("suggested-queries")) {
            chatInput.value = e.target.textContent.replace(/"/g, "");
            chatForm.dispatchEvent(new Event("submit"));
        }
    });

    function appendMessage(text, sender) {
        const msgDiv = document.createElement("div");
        msgDiv.className = `message ${sender}`;
        
        let formattedText = formatMarkdown(text);
        msgDiv.innerHTML = `<div class="message-content">${formattedText}</div>`;
        
        chatMessages.appendChild(msgDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function appendLoaderMessage() {
        const loaderId = "loader_" + Date.now();
        const msgDiv = document.createElement("div");
        msgDiv.className = "message assistant";
        msgDiv.id = loaderId;
        msgDiv.innerHTML = `
            <div class="message-content" style="display:flex; align-items:center; gap:0.5rem; color:var(--text-muted);">
                <div class="loader-spinner"></div>
                <span>Scanning document graphs & pages...</span>
            </div>
        `;
        chatMessages.appendChild(msgDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
        return loaderId;
    }

    function removeLoaderMessage(id) {
        const loader = document.getElementById(id);
        if (loader) loader.remove();
    }

    function formatMarkdown(text) {
        if (!text) return "";
        let html = text
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");
            
        html = html.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
        html = html.replace(/^\s*-\s+(.*?)$/gm, "<li>$1</li>");
        html = html.replace(/(<li>.*?<\/li>)/gs, "<ul>$1<\/ul>");
        html = html.replace(/<\/ul>\s*<ul>/g, "");
        html = html.replace(/\n\n/g, "</p><p>");
        html = html.replace(/\n/g, "<br>");
        
        return `<p>${html}</p>`.replace(/<p><br><\/p>/g, "").replace(/<p><\/p>/g, "");
    }

    // ----------------------------------------------------
    // INSPECTOR & SOURCES
    // ----------------------------------------------------
    function renderRetrievedSources(sources) {
        sourcesListContainer.innerHTML = "";
        
        if (!sources || sources.length === 0) {
            emptySourcesState.classList.remove("hidden");
            sourcesListContainer.classList.add("hidden");
            return;
        }

        emptySourcesState.classList.add("hidden");
        sourcesListContainer.classList.remove("hidden");

        sources.forEach((source, index) => {
            const card = document.createElement("div");
            card.className = "source-card";
            
            const docName = documents.find(d => d.id === source.document_id)?.filename || "Document";
            const badgeType = source.chunk_type === "visual" ? "visual-badge" : "text-badge";
            const badgeLabel = source.chunk_type === "visual" ? "Chart/Visual" : "Text Chunk";
            const pctSim = Math.round(source.similarity * 100);

            card.innerHTML = `
                <div class="source-card-header">
                    <div class="source-badges">
                        <span class="badge page-badge">Page ${source.page_num}</span>
                        <span class="badge ${badgeType}">${badgeLabel}</span>
                    </div>
                    <span class="score-badge">${pctSim}% match</span>
                </div>
                <div class="source-card-body">${source.content}</div>
                <div class="source-card-action">
                    ${source.chunk_type === 'visual' || source.image_path ? 
                        `<button class="action-btn" data-image="${source.image_path}" data-content="${encodeURIComponent(source.content)}" data-page="${source.page_num}">Inspect Chart</button>` : 
                        `<button class="action-btn" style="background:rgba(255,255,255,0.03); color:var(--text-secondary); border-color:transparent;" data-image="page-render" data-doc="${source.document_id}" data-page="${source.page_num}" data-content="${encodeURIComponent(source.content)}">Show Page</button>`
                    }
                </div>
            `;

            sourcesListContainer.appendChild(card);
        });

        switchTab("retrieved-sources");

        const actionBtns = sourcesListContainer.querySelectorAll(".action-btn");
        actionBtns.forEach(btn => {
            btn.addEventListener("click", () => {
                const targetImage = btn.dataset.image;
                const pageNum = btn.dataset.page;
                const content = decodeURIComponent(btn.dataset.content);

                if (targetImage === "page-render") {
                    const docId = btn.dataset.doc;
                    const computedPath = `/data/extracted_images/${docId}/page_${pageNum}.png`;
                    inspectImage(computedPath, `Page ${pageNum} Content:\n\n${content}`);
                } else {
                    inspectImage("/" + targetImage, `Page ${pageNum} Chart Summary:\n\n${content}`);
                }
            });
        });
    }

    function inspectImage(imagePath, captionText) {
        inspectedImage.src = imagePath;
        viewportDescription.textContent = captionText;
        
        // Reset scale and pan for Figma-style viewport
        zoomLevel = 1;
        panX = 0;
        panY = 0;
        inspectedImage.style.transition = "none";
        updateImageTransform();

        emptyVisualState.classList.add("hidden");
        visualViewportContainer.classList.remove("hidden");

        switchTab("visual-viewer");
    }

    tabButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            switchTab(btn.dataset.tab);
        });
    });

    function switchTab(tabId) {
        tabButtons.forEach(btn => {
            btn.classList.toggle("active", btn.dataset.tab === tabId);
        });
        tabContents.forEach(content => {
            content.classList.toggle("active", content.id === tabId);
        });
    }

    // ----------------------------------------------------
    // FIGMA-STYLE ZOOM & PAN (INTERACTIVE CANVAS)
    // ----------------------------------------------------
    let zoomLevel = 1;
    let panX = 0;
    let panY = 0;
    let isDragging = false;
    let startX = 0;
    let startY = 0;

    const imageZoomContainer = document.querySelector(".image-zoom-container");
    
    // Set default cursor and transform origin
    inspectedImage.style.transformOrigin = "center center";
    inspectedImage.style.cursor = "grab";

    function updateImageTransform() {
        inspectedImage.style.transform = `translate(${panX}px, ${panY}px) scale(${zoomLevel})`;
    }

    imageZoomContainer.addEventListener("mousedown", (e) => {
        if (!inspectedImage.src || inspectedImage.src.endsWith("/")) return;
        isDragging = true;
        startX = e.clientX - panX;
        startY = e.clientY - panY;
        inspectedImage.style.transition = "none";
        inspectedImage.style.cursor = "grabbing";
    });

    window.addEventListener("mousemove", (e) => {
        if (!isDragging) return;
        panX = e.clientX - startX;
        panY = e.clientY - startY;
        updateImageTransform();
    });

    window.addEventListener("mouseup", () => {
        if (isDragging) {
            isDragging = false;
            inspectedImage.style.cursor = "grab";
        }
    });

    // Support wheel-based zoom
    imageZoomContainer.addEventListener("wheel", (e) => {
        if (!inspectedImage.src || inspectedImage.src.endsWith("/")) return;
        e.preventDefault();
        
        const zoomFactor = 1.15;
        if (e.deltaY < 0) {
            zoomLevel = Math.min(zoomLevel * zoomFactor, 10); // cap at 10x
        } else {
            zoomLevel = Math.max(zoomLevel / zoomFactor, 0.5); // min 0.5x
        }
        
        inspectedImage.style.transition = "transform 0.1s ease-out";
        updateImageTransform();
    });

    zoomResetBtn.addEventListener("click", () => {
        zoomLevel = 1;
        panX = 0;
        panY = 0;
        inspectedImage.style.transition = "transform 0.2s ease-in-out";
        updateImageTransform();
    });

    // ----------------------------------------------------
    // THEME TOGGLE
    // ----------------------------------------------------
    const themeToggleBtn = document.getElementById("theme-toggle-btn");
    const themeIcon = themeToggleBtn.querySelector(".theme-icon");
    const themeText = themeToggleBtn.querySelector(".theme-text");

    // Load saved theme or default to dark
    const savedTheme = localStorage.getItem("theme") || "dark";
    if (savedTheme === "light") {
        enableLightTheme();
    } else {
        enableDarkTheme();
    }

    themeToggleBtn.addEventListener("click", () => {
        if (document.body.classList.contains("light-theme")) {
            enableDarkTheme();
        } else {
            enableLightTheme();
        }
    });

    function enableLightTheme() {
        document.body.classList.add("light-theme");
        themeIcon.textContent = "🌙";
        themeText.textContent = "Dark Mode";
        localStorage.setItem("theme", "light");
    }

    function enableDarkTheme() {
        document.body.classList.remove("light-theme");
        themeIcon.textContent = "☀️";
        themeText.textContent = "Light Mode";
        localStorage.setItem("theme", "dark");
    }

    // ----------------------------------------------------
    // TOAST NOTIFICATIONS
    // ----------------------------------------------------
    function showToast(message, type = "success") {
        toast.textContent = message;
        toast.className = `toast ${type}`;
        
        setTimeout(() => {
            toast.classList.remove("hidden");
        }, 100);

        setTimeout(() => {
            toast.classList.add("hidden");
        }, 4000);
    }
});
