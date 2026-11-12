/**
 * DukaPulse Kiosk POS & Ledger Frontend
 * Lightweight vanilla JavaScript client for African informal retail.
 */

(function () {
  "use strict";

  const state = {
    shopId: "shop_kibera_01",
    role: "owner",
    token: null,
    products: [],
    cart: new Map(), // productId -> { product, quantity }
  };

  // DOM Elements
  const el = {
    roleOwnerBtn: document.getElementById("role-owner-btn"),
    roleStaffBtn: document.getElementById("role-staff-btn"),
    authAlert: document.getElementById("auth-alert"),
    searchInput: document.getElementById("search-input"),
    searchResults: document.getElementById("search-results"),
    productGrid: document.getElementById("product-grid"),
    cartItems: document.getElementById("cart-items"),
    cartTotal: document.getElementById("cart-total"),
    checkoutBtn: document.getElementById("checkout-btn"),
    receiptBox: document.getElementById("receipt-box"),
    raceProductSelect: document.getElementById("race-product-select"),
    raceRunBtn: document.getElementById("race-run-btn"),
    raceResultsGrid: document.getElementById("race-results-grid"),
    raceNote: document.getElementById("race-note"),
    ledgerBody: document.getElementById("ledger-body"),
    toast: document.getElementById("toast"),
  };

  function showToast(message, isDanger = false, duration = 3500) {
    el.toast.textContent = message;
    el.toast.className = "toast-notice visible" + (isDanger ? " danger" : "");
    setTimeout(() => {
      el.toast.className = "toast-notice";
    }, duration);
  }

  async function apiRequest(path, options = {}) {
    const headers = options.headers || {};
    if (state.token) {
      headers["Authorization"] = `Bearer ${state.token}`;
    }
    if (options.body && typeof options.body === "object" && !(options.body instanceof FormData)) {
      headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(options.body);
    }
    options.headers = headers;

    const res = await fetch(path, options);
    return res;
  }

  // Auth: acquire dev token for active role
  async function setRole(newRole) {
    state.role = newRole;
    el.roleOwnerBtn.classList.toggle("active", newRole === "owner");
    el.roleStaffBtn.classList.toggle("active", newRole === "staff");

    try {
      const res = await fetch("/api/auth/token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          role: newRole,
          sub: `kiosk_${newRole}_clerk`,
          shop_id: state.shopId,
        }),
      });

      if (res.status === 403) {
        el.authAlert.textContent = "Run server with DEV_MODE_MOCK_AUTH=true";
        el.authAlert.classList.add("visible");
        state.token = null;
        return;
      }

      el.authAlert.classList.remove("visible");
      const data = await res.json();
      state.token = data.access_token;
      await loadProducts();
    } catch (err) {
      el.authAlert.textContent = "Authentication failed: " + err.message;
      el.authAlert.classList.add("visible");
    }
  }

  // Load product catalog and render grid & ledger
  async function loadProducts() {
    try {
      const res = await apiRequest(`/api/products?shop_id=${state.shopId}`);
      if (!res.ok) {
        throw new Error(`Failed to load products: ${res.status}`);
      }
      state.products = await res.json();
      renderProductGrid();
      renderStockLedger();
      populateRaceSelector();
    } catch (err) {
      showToast(err.message, true);
    }
  }

  function renderProductGrid() {
    el.productGrid.innerHTML = "";
    state.products.forEach((prod) => {
      const tile = document.createElement("div");
      tile.className = "product-tile";

      const isLow = prod.stock <= 10;
      tile.innerHTML = `
        <div class="product-tile-head">
          <div class="product-title">${escapeHtml(prod.name)}</div>
          <div class="product-category">${escapeHtml(prod.category)}</div>
        </div>
        <div class="product-tile-foot">
          <div>
            <div class="product-price num">KSh ${prod.price_ksh.toFixed(2)}</div>
            <div class="product-stock num ${isLow ? "low-stock" : ""}">Stock: ${prod.stock}</div>
          </div>
          <button class="btn btn-sm" data-add-id="${prod.id}">Add</button>
        </div>
      `;

      tile.querySelector("button").addEventListener("click", () => addToCart(prod.id));
      el.productGrid.appendChild(tile);
    });
  }

  function populateRaceSelector() {
    const prev = el.raceProductSelect.value;
    el.raceProductSelect.innerHTML = "";
    state.products.forEach((prod) => {
      const opt = document.createElement("option");
      opt.value = prod.id;
      opt.textContent = `${prod.name} (Stock: ${prod.stock})`;
      el.raceProductSelect.appendChild(opt);
    });
    if (prev) {
      el.raceProductSelect.value = prev;
    }
  }

  // Cart Management
  function addToCart(productId) {
    const prod = state.products.find((p) => p.id === productId);
    if (!prod) return;

    const existing = state.cart.get(productId);
    if (existing) {
      existing.quantity += 1;
    } else {
      state.cart.set(productId, { product: prod, quantity: 1 });
    }
    renderCart();
  }

  function updateCartQty(productId, delta) {
    const item = state.cart.get(productId);
    if (!item) return;
    item.quantity += delta;
    if (item.quantity <= 0) {
      state.cart.delete(productId);
    }
    renderCart();
  }

  function renderCart() {
    if (state.cart.size === 0) {
      el.cartItems.innerHTML = '<div class="cart-empty">Cart is empty. Select items from the catalog.</div>';
      el.cartTotal.textContent = "KSh 0.00";
      el.checkoutBtn.disabled = true;
      return;
    }

    el.cartItems.innerHTML = "";
    let grandTotal = 0.0;

    state.cart.forEach(({ product, quantity }) => {
      const lineTotal = product.price_ksh * quantity;
      grandTotal += lineTotal;

      const row = document.createElement("div");
      row.className = "cart-row";
      row.innerHTML = `
        <div>
          <div class="cart-item-name">${escapeHtml(product.name)}</div>
          <div class="cart-item-qty-wrap">
            <button class="btn btn-sm" data-dec="${product.id}">-</button>
            <span class="num">${quantity}</span>
            <button class="btn btn-sm" data-inc="${product.id}">+</button>
          </div>
        </div>
        <div class="num" style="font-weight:600;">KSh ${lineTotal.toFixed(2)}</div>
      `;

      row.querySelector("[data-dec]").addEventListener("click", () => updateCartQty(product.id, -1));
      row.querySelector("[data-inc]").addEventListener("click", () => updateCartQty(product.id, 1));
      el.cartItems.appendChild(row);
    });

    el.cartTotal.textContent = `KSh ${grandTotal.toFixed(2)}`;
    el.checkoutBtn.disabled = false;
  }

  // Checkout with Lipa na M-PESA
  async function handleCheckout() {
    if (state.cart.size === 0) return;

    el.checkoutBtn.disabled = true;
    el.checkoutBtn.textContent = "Processing M-PESA…";

    const items = [];
    state.cart.forEach(({ product, quantity }) => {
      items.push({ product_id: product.id, quantity });
    });

    try {
      const res = await apiRequest("/api/sales", {
        method: "POST",
        body: {
          shop_id: state.shopId,
          items: items,
          payment_method: "M-PESA",
        },
      });

      if (res.status === 409) {
        const errData = await res.json();
        showToast(errData.detail || "Oversell attempt blocked by row lock", true);
        return;
      }

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        showToast(errData.detail || `Checkout failed (${res.status})`, true);
        return;
      }

      const receipt = await res.json();
      renderReceipt(receipt);
      state.cart.clear();
      renderCart();
      await loadProducts();
      showToast("M-PESA payment confirmed");
    } catch (err) {
      showToast(err.message, true);
    } finally {
      el.checkoutBtn.disabled = false;
      el.checkoutBtn.textContent = "Checkout — Lipa na M-PESA";
    }
  }

  function renderReceipt(receipt) {
    el.receiptBox.innerHTML = `
      <div class="receipt-title">Sale Confirmed · Lipa na M-PESA</div>
      <div class="receipt-line"><span>Sale ID</span><span class="num">${escapeHtml(receipt.sale_id.slice(0, 13))}…</span></div>
      <div class="receipt-line"><span>Items Purchased</span><span class="num">${receipt.items.length} lines</span></div>
      <div class="receipt-line"><span>Total Paid</span><span class="num" style="font-weight:700;">KSh ${receipt.total_ksh.toFixed(2)}</span></div>
      <div class="receipt-line"><span>Remaining Stock</span><span class="num">${receipt.remaining_stock} units</span></div>
    `;
    el.receiptBox.classList.add("visible");
  }

  // Semantic Search
  let searchDebounceTimer = null;
  el.searchInput.addEventListener("input", (e) => {
    clearTimeout(searchDebounceTimer);
    const query = e.target.value.trim();
    if (!query) {
      el.searchResults.classList.remove("visible");
      el.searchResults.innerHTML = "";
      return;
    }
    searchDebounceTimer = setTimeout(() => executeSearch(query), 200);
  });

  async function executeSearch(query) {
    try {
      const res = await apiRequest(
        `/api/products/search?q=${encodeURIComponent(query)}&k=5&shop_id=${state.shopId}`
      );
      if (!res.ok) return;
      const matches = await res.json();

      if (matches.length === 0) {
        el.searchResults.innerHTML = '<div style="padding:10px 14px;color:var(--muted);font-size:12px;">No matches found.</div>';
        el.searchResults.classList.add("visible");
        return;
      }

      el.searchResults.innerHTML = "";
      matches.forEach((item) => {
        const row = document.createElement("div");
        row.className = "search-row";

        const pct = Math.max(0, Math.min(100, Math.round(item.similarity * 100)));
        row.innerHTML = `
          <div class="search-row-left">
            <div class="search-product-name">${escapeHtml(item.name)}</div>
            <div class="search-meta">
              <span class="num" style="font-weight:600;">KSh ${item.price_ksh.toFixed(2)}</span>
              <div class="similarity-metric">
                <span class="num">${item.similarity.toFixed(4)}</span>
                <div class="similarity-bar-bg">
                  <div class="similarity-bar-fill" style="width:${pct}%;"></div>
                </div>
              </div>
            </div>
          </div>
          <button class="btn btn-sm" data-add-id="${item.product_id}">Add</button>
        `;

        row.querySelector("button").addEventListener("click", () => addToCart(item.product_id));
        el.searchResults.appendChild(row);
      });
      el.searchResults.classList.add("visible");
    } catch {
      // Non-blocking search error
    }
  }

  // Concurrency Oversell Race Simulation
  async function runConcurrencyRace() {
    const productId = el.raceProductSelect.value;
    if (!productId) return;

    el.raceRunBtn.disabled = true;
    el.raceRunBtn.textContent = "Racing 2 Threads…";

    try {
      const res = await apiRequest("/api/demo/oversell-race", {
        method: "POST",
        body: { product_id: productId, shop_id: state.shopId },
      });

      if (res.status === 403) {
        showToast("DEV_MODE_MOCK_AUTH is disabled on server", true);
        return;
      }

      const data = await res.json();
      renderRaceResults(data.attempts, data.note);
      await loadProducts();
    } catch (err) {
      showToast("Race failed: " + err.message, true);
    } finally {
      el.raceRunBtn.disabled = false;
      el.raceRunBtn.textContent = "Simulate 2 Concurrent M-PESA Orders";
    }
  }

  function renderRaceResults(attempts, note) {
    el.raceResultsGrid.innerHTML = "";
    attempts.forEach((att) => {
      const isSuccess = att.outcome === "success";
      const card = document.createElement("div");
      card.className = "race-card " + (isSuccess ? "success-card" : "rejected-card");

      card.innerHTML = `
        <div class="race-card-head">${isSuccess ? "Order Claimed (HTTP 200)" : "Order Blocked (HTTP 409)"}</div>
        <div class="race-card-body">
          <div>Clerk / Order Thread: <span class="num">#${att.worker}</span></div>
          ${
            isSuccess
              ? `<div>Outcome: <strong>Success</strong></div><div>Remaining Stock: <span class="num">${att.remaining_stock}</span></div>`
              : `<div>Outcome: <strong>Conflict (Rejected)</strong></div><div>Constraint: <code>${escapeHtml(att.error || "Oversell blocked")}</code></div>`
          }
        </div>
      `;
      el.raceResultsGrid.appendChild(card);
    });

    el.raceNote.textContent = note || "";
  }

  // Stock Ledger Table
  function renderStockLedger() {
    el.ledgerBody.innerHTML = "";
    state.products.forEach((prod) => {
      const tr = document.createElement("tr");

      const isOwner = state.role === "owner";
      const marginCell = isOwner && prod.margin_ksh !== null
        ? `<span class="num">KSh ${prod.margin_ksh.toFixed(2)}</span>`
        : `<span class="num" style="color:var(--muted);">—</span>`;

      tr.innerHTML = `
        <td><strong>${escapeHtml(prod.name)}</strong></td>
        <td style="color:var(--muted);">${escapeHtml(prod.category)}</td>
        <td class="num table-num">${prod.stock}</td>
        <td class="num table-num">KSh ${prod.price_ksh.toFixed(2)}</td>
        <td class="num table-num">${marginCell}</td>
        <td style="text-align:right;">
          <button class="btn btn-sm" data-restock="${prod.id}">Restock +12</button>
        </td>
      `;

      tr.querySelector("[data-restock]").addEventListener("click", () => handleRestock(prod.id, tr));
      el.ledgerBody.appendChild(tr);
    });
  }

  async function handleRestock(productId, rowElement) {
    rowElement.classList.add("is-loading");

    try {
      const res = await apiRequest("/api/inventory/restock", {
        method: "POST",
        body: {
          shop_id: state.shopId,
          product_id: productId,
          quantity: 12,
        },
      });

      if (res.status === 403) {
        showToast("HTTP 403 Forbidden: Owner role required to restock inventory", true);
        return;
      }

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        showToast(err.detail || "Restock failed", true);
        return;
      }

      showToast("Restocked +12 units successfully");
      await loadProducts();
    } catch (err) {
      showToast(err.message, true);
    } finally {
      rowElement.classList.remove("is-loading");
    }
  }

  function escapeHtml(str) {
    if (!str) return "";
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // Bind Events
  el.roleOwnerBtn.addEventListener("click", () => setRole("owner"));
  el.roleStaffBtn.addEventListener("click", () => setRole("staff"));
  el.checkoutBtn.addEventListener("click", handleCheckout);
  el.raceRunBtn.addEventListener("click", runConcurrencyRace);

  // Initialize
  setRole("owner");
})();
