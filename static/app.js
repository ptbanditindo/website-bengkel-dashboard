/* AI Bengkel — local admin UI (H8F).
 * Single-page app. Token is kept in sessionStorage and never sent via URL.
 * All data endpoints require `Authorization: Bearer <token>`.
 */

(function () {
  "use strict";

  const TOKEN_KEY = "ai_bengkel_ui_token";

  const state = {
    token: sessionStorage.getItem(TOKEN_KEY) || null,
    view: "dashboard",
    vehicleQuery: "",
    vehiclePage: 0,
    pageSize: 10,
    currentVehicleId: null,
    currentRecordId: null,
    warrantyList: [],
    warrantyQuery: "",
    warrantyFilter: "all",
    serviceList: [],
    serviceQuery: "",
    serviceFilter: "all",
    jasaList: [],
    stockList: [],
    stockQuery: "",
    hjList: [],
    hjQuery: "",
    waQuery: "",
    waFilter: "",
    waDateFilter: "all",
    currentWaId: null,
    waContacts: [],
  };

  const $ = (sel) => document.querySelector(sel);

  let _modalCallback = null;

  function showModal(message, fields, okText, danger, onOk, hideCancel) {
    $("#modal-message").textContent = message || "";
    $("#modal-message").classList.toggle("hidden", !message);
    var container = $("#modal-fields");
    container.innerHTML = "";
    (fields || []).forEach(function (f) {
      var el;
      if (f.type === "select") {
        el = document.createElement("select");
        (f.options || []).forEach(function (opt) {
          var o = document.createElement("option");
          o.value = opt.value;
          o.textContent = opt.label;
          if (String(opt.value) === String(f.value)) o.selected = true;
          el.appendChild(o);
        });
      } else {
        el = document.createElement("input");
        el.type = f.type || "text";
        el.placeholder = f.placeholder || "";
        el.value = f.value || "";
      }
      el.dataset.key = f.key;
      container.appendChild(el);
    });
    $("#modal-cancel").classList.toggle("hidden", !!hideCancel);
    $("#modal-ok").textContent = okText || "OK";
    $("#modal-ok").className = "btn " + (danger ? "danger" : "primary");
    _modalCallback = onOk;
    $("#app-modal").classList.remove("hidden");
    var first = container.querySelector("input, select");
    if (first) first.focus();
  }

  function hideModal() {
    $("#app-modal").classList.add("hidden");
    _modalCallback = null;
  }

  function showError(message) {
    showModal(message || "Terjadi kesalahan.", [], "OK", false, null, true);
  }

  // ---------------------------------------------------------------------------
  // API helper
  // ---------------------------------------------------------------------------
  class ApiError extends Error {
    constructor(status, message) {
      super(message);
      this.status = status;
    }
  }

  async function api(path, options) {
    options = options || {};
    const headers = Object.assign({}, options.headers || {});
    if (state.token) headers["Authorization"] = "Bearer " + state.token;

    let resp;
    try {
      resp = await fetch(path, Object.assign({}, options, { headers: headers }));
    } catch (err) {
      throw new ApiError(0, "Tidak dapat terhubung ke server lokal.");
    }

    if (resp.status === 401) {
      clearToken();
      showLogin("Token tidak valid atau sesi berakhir. Silakan masuk kembali.");
      throw new ApiError(401, "Unauthorized");
    }
    if (resp.status === 503) {
      throw new ApiError(503, "Autentikasi API belum dikonfigurasi (UI_ACCESS_TOKEN kosong).");
    }

    let data = null;
    const ct = resp.headers.get("content-type") || "";
    if (ct.indexOf("application/json") !== -1) {
      data = await resp.json();
    }

    if (!resp.ok) {
      const detail = data && data.detail ? data.detail : "Permintaan gagal (status " + resp.status + ").";
      throw new ApiError(resp.status, detail);
    }
    return data;
  }

  // ---------------------------------------------------------------------------
  // Auth
  // ---------------------------------------------------------------------------
  function clearToken() {
    sessionStorage.removeItem(TOKEN_KEY);
    state.token = null;
  }

  function showLogin(message) {
    $("#app-view").classList.add("hidden");
    $("#login-view").classList.remove("hidden");
    const err = $("#login-error");
    if (message) {
      err.textContent = message;
      err.classList.remove("hidden");
    } else {
      err.classList.add("hidden");
    }
    $("#token-input").focus();
  }

  function showApp() {
    $("#login-view").classList.add("hidden");
    $("#app-view").classList.remove("hidden");
  }

  function logout() {
    clearToken();
    state.view = "dashboard";
    showLogin();
  }

  // ---------------------------------------------------------------------------
  // Router / navigation
  // ---------------------------------------------------------------------------
  const TITLES = {
    dashboard: "Dashboard",
    vehicles: "Kendaraan",
    vehicleDetail: "Detail Kendaraan",
    vehicleEdit: "Edit Kendaraan",
    serviceDetail: "Detail Riwayat Servis",
    recentServices: "Riwayat Servis",
    garansi: "Garansi",
    stock: "Stok",
    hargaJasa: "Harga Jasa",
    incomplete: "Data Belum Lengkap",
    backup: "Backup & Restore",
    waCs: "WhatsApp CS",
    waInbox: "WhatsApp CS - Inbox",
    waConversation: "WhatsApp CS - Percakapan",
    integrations: "Pengaturan Integrasi",
  };

  const FIELD_LABELS = {
    nama_client: "Nama pelanggan",
    nomor_wa: "Nomor WhatsApp",
    jenis_mobil: "Jenis mobil",
    tahun_mobil: "Tahun mobil",
    alamat_client: "Alamat",
  };

  function navigate(view) {
    state.view = view;
    stopWaPoll();
    $("#page-title").textContent = TITLES[view] || "AI Bengkel";
    document.querySelectorAll(".nav-item").forEach(function (b) {
      b.classList.toggle("active", b.dataset.view === view);
    });
    render();
  }

  function render() {
    switch (state.view) {
      case "dashboard": return renderDashboard();
      case "vehicles": return renderVehicles();
      case "vehicleDetail": return renderVehicleDetail();
      case "vehicleEdit": return renderVehicleEdit();
      case "serviceDetail": return renderServiceDetail();
      case "recentServices": return renderRecentServices();
      case "garansi": return renderGaransi();
      case "stock": return renderStock();
      case "hargaJasa": return renderHargaJasa();
      case "incomplete": return renderIncomplete();
      case "backup": return renderBackup();
      case "waCs": return renderWaCs();
      case "waInbox": return renderWaInbox();
      case "waConversation": return renderWaConversation();
      case "integrations": return renderIntegrations();
      default: return renderDashboard();
    }
  }

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------
  function escapeHtml(value) {
    if (value === null || value === undefined) return "";
    return String(value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function fmtDate(iso) {
    if (!iso) return "–";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short" });
  }

  function fmtMoney(value) {
    if (value === null || value === undefined || value === "") return "–";
    const n = Number(value);
    if (isNaN(n)) return value;
    return "Rp " + n.toLocaleString("id-ID");
  }

  function display(value) {
    return (value === null || value === undefined || value === "") ? "Belum diisi" : value;
  }

  function setContent(html) {
    $("#content").innerHTML = html;
  }

  function loading(label) {
    return '<div class="muted"><span class="spinner"></span>' + escapeHtml(label) + "</div>";
  }

  // ---------------------------------------------------------------------------
  // Dashboard
  // ---------------------------------------------------------------------------
  async function renderDashboard() {
    setContent('<div class="cards">' +
      '<div class="card clickable" data-nav="vehicles"><div class="card-label">Total Kendaraan</div><div class="card-value" id="dash-vehicles">–</div></div>' +
      '<div class="card clickable" data-nav="recentServices"><div class="card-label">Total Riwayat Servis</div><div class="card-value" id="dash-records">–</div></div>' +
      '<div class="card clickable" data-nav="incomplete"><div class="card-label">Data Belum Lengkap</div><div class="card-value" id="dash-incomplete">–</div></div>' +
      "</div>" +
      '<section class="panel"><h2>Ringkasan Keuangan</h2>' +
      '<div class="toolbar"><select id="profit-period">' +
      '<option value="today">Hari ini</option>' +
      '<option value="week">Minggu ini</option>' +
      '<option value="month" selected>Bulan ini</option>' +
      '<option value="year">Tahun ini</option>' +
      '<option value="all">Seluruhnya</option>' +
      "</select></div>" +
      '<div class="cards finance">' +
      '<div class="card clickable" data-profit="jasa"><div class="card-label">Keuntungan Jasa</div><div class="card-value" id="dash-profit-jasa">–</div>' +
        '<div class="card-lines"><div class="fline"><span class="k">Pendapatan jasa</span><span class="v" id="jasa-pendapatan">–</span></div>' +
        '<div class="fline"><span class="k">- Modal jasa</span><span class="v" id="jasa-modal">–</span></div></div></div>' +
      '<div class="card clickable" data-profit="barang"><div class="card-label">Keuntungan Barang</div><div class="card-value" id="dash-profit-barang">–</div>' +
        '<div class="card-lines"><div class="fline"><span class="k">Omset kotor barang</span><span class="v" id="barang-omset">–</span></div>' +
        '<div class="fline"><span class="k">- Modal barang</span><span class="v" id="barang-modal">–</span></div></div></div>' +
      '<div class="card clickable" data-profit="barang"><div class="card-label">Omset Kotor Barang</div><div class="card-value" id="dash-omset-barang">–</div>' +
        '<div class="card-lines"><div class="fline"><span class="k">Modal barang</span><span class="v" id="omset-modal">–</span></div>' +
        '<div class="fline"><span class="k">+ Keuntungan barang</span><span class="v" id="omset-untung">–</span></div></div></div>' +
      '<div class="card clickable" data-profit="all"><div class="card-label">Omset Kotor Perusahaan</div><div class="card-value" id="dash-omset-perusahaan">–</div>' +
        '<div class="card-lines"><div class="fline"><span class="k">Omset kotor barang</span><span class="v" id="perusahaan-omset">–</span></div>' +
        '<div class="fline"><span class="k">+ Keuntungan jasa</span><span class="v" id="perusahaan-jasa">–</span></div></div></div>' +
      "</div>" +
      '<div class="chart-block"><h3>Grafik Keuangan</h3><div id="profit-chart" class="chart-holder"><span class="muted">Memuat...</span></div></div>' +
      "</section>");

    try {
      const d = await api("/api/dashboard");
      $("#dash-vehicles").textContent = d.vehicle_count;
      $("#dash-records").textContent = d.service_record_count;
      $("#dash-incomplete").textContent = d.incomplete_vehicles_count + d.warranty_incomplete_count;
    } catch (e) {
      // stat cards keep "–" on failure
    }

    await loadProfit();
  }

  async function loadProfit() {
    const period = $("#profit-period").value;
    const na = "–";
    try {
      const p = await api("/api/dashboard/profit?period=" + encodeURIComponent(period));
      const jasa = p.keuntungan_jasa;
      const barang = p.keuntungan_barang;
      const modal = p.modal_barang;
      const omset = p.omset_barang;
      const perusahaan = (omset != null && jasa != null) ? (Number(omset) + Number(jasa)) : null;

      $("#dash-profit-jasa").textContent = fmtMoney(jasa);
      $("#dash-profit-barang").textContent = fmtMoney(barang);
      $("#dash-omset-barang").textContent = fmtMoney(omset);
      $("#dash-omset-perusahaan").textContent = fmtMoney(perusahaan);

      $("#jasa-pendapatan").textContent = fmtMoney(jasa);
      $("#jasa-modal").textContent = fmtMoney(0);
      $("#barang-omset").textContent = fmtMoney(omset);
      $("#barang-modal").textContent = fmtMoney(modal);
      $("#omset-modal").textContent = fmtMoney(modal);
      $("#omset-untung").textContent = fmtMoney(barang);
      $("#perusahaan-omset").textContent = fmtMoney(omset);
      $("#perusahaan-jasa").textContent = fmtMoney(jasa);
    } catch (e) {
      ["dash-profit-jasa", "dash-profit-barang", "dash-omset-barang", "dash-omset-perusahaan",
       "jasa-pendapatan", "jasa-modal", "barang-omset", "barang-modal",
       "omset-modal", "omset-untung", "perusahaan-omset", "perusahaan-jasa"].forEach(function (id) {
        const el = $("#" + id); if (el) el.textContent = na;
      });
    }
    await loadChart();
  }

  async function loadChart() {
    const el = $("#profit-chart");
    if (!el) return;
    const period = $("#profit-period").value;
    try {
      const items = await api("/api/profit/history?kind=barang&period=" + encodeURIComponent(period));
      renderChart(el, items, period);
    } catch (e) {
      el.innerHTML = '<span class="muted">Grafik tidak tersedia.</span>';
    }
  }

  function renderChart(el, items, period) {
    if (!items || !items.length) {
      el.innerHTML = '<span class="muted">Belum ada data transaksi.</span>';
      return;
    }
    const buckets = {};
    items.forEach(function (i) {
      const key = bucketKey(i.tanggal, period);
      const o = Number(i.harga_jual) || 0;
      const m = Number(i.modal) || 0;
      if (!buckets[key]) buckets[key] = { omset: 0, modal: 0 };
      buckets[key].omset += o;
      buckets[key].modal += m;
    });
    const keys = Object.keys(buckets).sort();
    const max = Math.max(1, ...keys.map(function (k) { return buckets[k].omset; }));
    const bars = keys.map(function (k) {
      const o = buckets[k].omset;
      const m = Math.min(buckets[k].modal, o);
      const oh = Math.round((o / max) * 100);
      const mh = Math.round((m / max) * 100);
      const uh = oh - mh;
      return '<div class="bar-wrap" title="' + escapeHtml(k + " - Omset " + fmtMoney(o)) + '">' +
        '<div class="bar-stack">' +
        '<div class="bar untung" style="height:' + uh + '%"></div>' +
        '<div class="bar modal" style="height:' + mh + '%"></div>' +
        '</div>' +
        '<span class="bar-label">' + escapeHtml(k) + '</span>' +
        '</div>';
    }).join("");
    el.innerHTML = '<div class="chart">' + bars + '</div>' +
      '<div class="chart-legend"><span class="lg untung"></span>Keuntungan <span class="lg modal"></span>Modal</div>';
  }

  function bucketKey(iso, period) {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso).slice(0, 10);
    if (period === "year" || period === "all") {
      return (d.getMonth() + 1) + "-" + d.getFullYear();
    }
    return d.getDate() + "-" + (d.getMonth() + 1);
  }

  async function renderProfitHistory(kind) {
    var period = ($("#profit-period") ? $("#profit-period").value : "all");
    setContent('<div class="panel">' + loading("Memuat history...") + "</div>");
    try {
      let items, title;
      if (kind === "all") {
        const jasa = await api("/api/profit/history?kind=jasa&period=" + encodeURIComponent(period));
        const barang = await api("/api/profit/history?kind=barang&period=" + encodeURIComponent(period));
        items = jasa.concat(barang).sort(function (a, b) {
          return new Date(b.tanggal) - new Date(a.tanggal);
        });
        title = "History Keuangan";
      } else {
        items = await api("/api/profit/history?kind=" + kind + "&period=" + encodeURIComponent(period));
        title = (kind === "jasa") ? "History Keuntungan Jasa" : "History Keuntungan Barang";
      }
      if (!items.length) {
        setContent('<div class="panel"><h2>' + title + '</h2><p class="muted">Belum ada transaksi.</p><div class="toolbar"><button class="btn ghost" data-nav="dashboard">Kembali</button></div></div>');
        return;
      }
      const rows = items.map(function (i) {
        return "<tr><td>" + fmtDate(i.tanggal) + "</td><td>" + escapeHtml(i.nama) + "</td><td>" + fmtMoney(i.harga_jual) + "</td><td>" + fmtMoney(i.modal) + "</td><td>" + fmtMoney(i.keuntungan) + "</td></tr>";
      }).join("");
      setContent(
        '<div class="panel"><h2>' + title + '</h2>' +
        '<div class="toolbar"><button class="btn ghost" data-nav="dashboard">Kembali</button></div>' +
        '<table class="table"><thead><tr><th>Tanggal</th><th>Nama</th><th>Harga Jual</th><th>Modal</th><th>Untung Bersih</th></tr></thead><tbody>' +
        rows + "</tbody></table></div>"
      );
    } catch (e) {
      setContent('<div class="panel"><p class="error">' + escapeHtml(e.message) + "</p></div>");
    }
  }

  function warrantyStatus(r) {
    if (r.bergaransi === true) {
      if (r.garansi_sampai) {
        var d = new Date(r.garansi_sampai);
        var today = new Date();
        today.setHours(0, 0, 0, 0);
        if (d < today) {
          return '<span class="badge danger">Garansi Kadaluarsa (' + fmtDateOnly(r.garansi_sampai) + ")</span>";
        }
        return '<span class="badge ok">Bergaransi s/d ' + fmtDateOnly(r.garansi_sampai) + "</span>";
      }
      return '<span class="badge ok">Bergaransi</span>';
    }
    if (r.bergaransi === false) {
      return '<span class="badge off">Tidak bergaransi</span>';
    }
    return '<span class="badge warn">Garansi belum diisi</span>';
  }

  function claimStatus(r) {
    return (r.status_klaim === "Sudah claim")
      ? '<span class="badge warn">Sudah claim' + (r.tanggal_klaim ? " · " + fmtDateOnly(r.tanggal_klaim) : "") + "</span>"
      : '<span class="badge on">Belum claim</span>';
  }

  function warrantyBadge(r) {
    return warrantyStatus(r) + " " + claimStatus(r);
  }

  function warrantyText(r) {
    if (r.bergaransi === true) {
      if (r.garansi_sampai) {
        var d = new Date(r.garansi_sampai);
        var today = new Date();
        today.setHours(0, 0, 0, 0);
        if (d < today) return "Garansi Kadaluarsa (" + fmtDateOnly(r.garansi_sampai) + ")";
        return "Bergaransi s/d " + fmtDateOnly(r.garansi_sampai);
      }
      return "Bergaransi";
    }
    if (r.bergaransi === false) return "Tidak bergaransi";
    return "Belum diisi";
  }

  function claimText(r) {
    return (r.status_klaim === "Sudah claim" && r.tanggal_klaim)
      ? "Sudah claim (" + fmtDateOnly(r.tanggal_klaim) + ")"
      : r.status_klaim;
  }

  // ---------------------------------------------------------------------------
  // Recent services (10 latest)
  // ---------------------------------------------------------------------------
  async function renderRecentServices() {
    setContent('<div class="panel">' +
      "<h2>Riwayat Servis</h2>" +
      '<div id="services-result">' + loading("Memuat riwayat...") + "</div>" +
      "</div>");
    try {
      state.serviceList = await api("/api/service-records?limit=500");
      state.jasaList = await api("/api/harga-jasa");
      renderServiceView();
    } catch (e) {
      $("#services-result").innerHTML = '<p class="error">' + escapeHtml(e.message) + "</p>";
    }
  }

  function serviceCards(list) {
    return '<div class="vcard-grid">' +
      list.map(function (r) {
        return '<div class="vcard">' +
          '<div class="vcard-top">' +
          '<div class="vcard-plate">' + escapeHtml(r.nopol) + '</div>' +
          '<span class="act-total">' + fmtMoney(r.total_servis) + '</span>' +
          '</div>' +
          '<div class="vcard-line"><strong>' + escapeHtml(r.jasa || "\u2014") + '</strong></div>' +
          '<div class="vcard-line muted">' + fmtDate(r.waktu_service) + '</div>' +
          '<div class="vcard-line">' +
          '<button class="btn sm" data-record="' + r.id + '">Detail</button>' +
          '</div>' +
          '</div>';
      }).join('') + '</div>';
  }

  function renderServiceView() {
    var list = state.serviceList || [];
    var q = (state.serviceQuery || "").trim().toLowerCase();
    var filter = state.serviceFilter || "all";

    var filtered = list.filter(function (r) {
      if (!matchesJasaFilter(r, filter)) return false;
      if (q) {
        var hay = ((r.nopol || "") + " " + (r.nama_client || "") + " " + (r.jasa || "")).toLowerCase();
        if (hay.indexOf(q) === -1) return false;
      }
      return true;
    });

    var toolbar = '<div class="toolbar">' + filterDropdown("service-filter", filter, jasaOptions()) +
      '<input type="text" id="services-search" placeholder="Cari nama pemilik / plat / nama jasa..." value="' + escapeHtml(state.serviceQuery || "") + '"></div>';

    setContent('<div class="panel"><h2>Riwayat Servis</h2>' + toolbar +
      (filtered.length ? serviceCards(filtered) : '<p class="muted">Tidak ada riwayat servis.</p>') +
      '</div>');
  }

  function editWarranty(btn) {
    var id = btn.getAttribute("data-warranty-edit");
    var current = btn.getAttribute("data-current") || "";
    var curB = btn.getAttribute("data-bergaransi") || "";
    showModal("Apakah servis ini bergaransi?",
      [{ key: "bergaransi", type: "select", value: curB, options: [
        { value: "1", label: "Ya, bergaransi" },
        { value: "0", label: "Tidak bergaransi" },
      ] }],
      "Lanjut", false, function (v) {
        if (v.bergaransi === "0") {
          api("/api/service-records/" + id + "/warranty", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ bergaransi: false, garansi_sampai: null }),
          }).then(function () { render(); })
            .catch(function (e) { showError("Gagal mengubah garansi: " + e.message); });
          return;
        }
        showModal("Sampai kapan garansi berlaku? (YYYY-MM-DD / DD-MM-YYYY / hari ini / 2 Agustus 2026)",
          [{ key: "garansi", value: current, placeholder: "YYYY-MM-DD" }],
          "Simpan", false, function (v2) {
            var val = (v2.garansi || "").trim();
            api("/api/service-records/" + id + "/warranty", {
              method: "PUT",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ bergaransi: true, garansi_sampai: val || null }),
            }).then(function () { render(); })
              .catch(function (e) { showError("Gagal mengubah garansi: " + e.message); });
          });
      });
  }

  // ---------------------------------------------------------------------------
  // Stock
  // ---------------------------------------------------------------------------
  async function renderStock() {
    setContent('<div class="panel"><h2>Stok</h2>' +
      '<div class="toolbar"><input type="text" id="stock-search" placeholder="Cari nama / kode barang..." value="' + escapeHtml(state.stockQuery || "") + '"></div>' +
      '<div id="stock-table">' + loading("Memuat stok...") + "</div>" +
      '<div class="add-row"><button class="btn sm" data-stock-add="1">Tambah Stok</button></div></div>');
    try {
      state.stockList = await api("/api/stock");
      renderStockTable();
    } catch (e) {
      $("#stock-table").innerHTML = '<p class="error">' + escapeHtml(e.message) + "</p>";
    }
  }

  function renderStockTable() {
    const list = state.stockList || [];
    const q = (state.stockQuery || "").trim().toLowerCase();
    const filtered = list.filter(function (s) {
      if (!q) return true;
      return ((s.nama || "") + " " + (s.kode || "")).toLowerCase().indexOf(q) !== -1;
    });
    if (!filtered.length) {
      $("#stock-table").innerHTML = '<p class="muted">' + (list.length ? "Tidak ada stok yang cocok." : "Belum ada stok.") + "</p>";
      return;
    }
    const rows = filtered.map(function (s) {
      return "<tr>" +
        "<td>" + escapeHtml(display(s.kode)) + "</td>" +
        "<td>" + escapeHtml(s.nama) + "</td>" +
        "<td>" + escapeHtml(s.jumlah) + "</td>" +
        "<td>" + fmtMoney(s.harga_modal) + "</td>" +
        "<td>" + fmtMoney(s.harga_jual) + "</td>" +
        "<td><strong>" + fmtMoney(s.keuntungan) + "</strong></td>" +
        '<td><button class="btn sm" data-stock-edit="' + s.id + '" data-kode="' + escapeHtml(s.kode || "") + '" data-nama="' + escapeHtml(s.nama) + '" data-jumlah="' + escapeHtml(s.jumlah) + '" data-modal="' + escapeHtml(s.harga_modal || "") + '" data-jual="' + escapeHtml(s.harga_jual || "") + '">Ubah</button> ' +
        '<button class="btn sm danger" data-stock-delete="' + s.id + '">Hapus</button></td>' +
        "</tr>";
    }).join("");
    $("#stock-table").innerHTML = '<table class="table"><thead><tr><th>Kode</th><th>Nama</th><th>Stok</th><th>Modal</th><th>Jual</th><th>Keuntungan</th><th></th></tr></thead><tbody>' +
      rows + "</tbody></table>";
  }

  function startStockAdd(btn) {
    var row = btn.closest(".add-row");
    row.innerHTML =
      '<input type="text" data-stock-kode placeholder="Kode">' +
      '<input type="text" data-stock-name placeholder="Nama barang">' +
      '<input type="number" data-stock-jumlah value="0" min="0" style="width:70px">' +
      '<input type="text" data-stock-modal placeholder="Harga modal">' +
      '<input type="text" data-stock-jual placeholder="Harga jual">' +
      '<button class="btn sm primary" data-stock-add-save="1">Simpan</button>' +
      '<button class="btn sm ghost" data-stock-add-cancel="1">Batal</button>';
    row.querySelector('[data-stock-name]').focus();
  }

  async function saveStockAdd(btn) {
    var row = btn.closest(".add-row");
    var kode = row.querySelector('[data-stock-kode]').value.trim();
    var nama = row.querySelector('[data-stock-name]').value.trim();
    var jumlah = row.querySelector('[data-stock-jumlah]').value.trim();
    var modal = row.querySelector('[data-stock-modal]').value.trim();
    var jual = row.querySelector('[data-stock-jual]').value.trim();
    if (!nama) { showError("Nama barang wajib diisi."); return; }
    btn.disabled = true;
    try {
      await api("/api/stock", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kode: kode, nama: nama, jumlah: parseInt(jumlah, 10) || 0, harga_modal: modal, harga_jual: jual }),
      });
      navigate("stock");
    } catch (e) {
      showError("Gagal menambah: " + e.message);
      navigate("stock");
    }
  }

  function editStock(btn) {
    var id = btn.getAttribute("data-stock-edit");
    var kode = btn.getAttribute("data-kode") || "";
    var nama = btn.getAttribute("data-nama") || "";
    var jumlah = btn.getAttribute("data-jumlah") || "0";
    var modal = btn.getAttribute("data-modal") || "";
    var jual = btn.getAttribute("data-jual") || "";
    showModal("Ubah stok", [
      { key: "kode", value: kode, placeholder: "Kode" },
      { key: "nama", value: nama, placeholder: "Nama barang" },
      { key: "jumlah", value: jumlah, placeholder: "Jumlah stok", type: "number" },
      { key: "modal", value: modal, placeholder: "Harga modal" },
      { key: "jual", value: jual, placeholder: "Harga jual" },
    ], "Simpan", false, function (v) {
      api("/api/stock/" + id, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kode: v.kode, nama: v.nama, jumlah: parseInt(v.jumlah, 10) || 0, harga_modal: v.modal, harga_jual: v.jual }),
      }).then(function () { navigate("stock"); })
        .catch(function (e) { showError("Gagal menyimpan: " + e.message); });
    });
  }

  function deleteStock(btn) {
    var id = btn.getAttribute("data-stock-delete");
    showModal("Hapus stok ini?", [], "Ya, Hapus", true, function () {
      api("/api/stock/" + id, { method: "DELETE" }).then(function () {
        navigate("stock");
      }).catch(function (e) {
        showError("Gagal menghapus: " + e.message);
      });
    });
  }

  // ---------------------------------------------------------------------------
  // Harga Jasa
  // ---------------------------------------------------------------------------
  async function renderHargaJasa() {
    setContent('<div class="panel"><h2>Harga Jasa</h2>' +
      '<div class="toolbar"><input type="text" id="hj-search" placeholder="Cari nama jasa..." value="' + escapeHtml(state.hjQuery || "") + '"></div>' +
      '<div id="hj-table">' + loading("Memuat harga jasa...") + "</div>" +
      '<div class="add-row"><button class="btn sm" data-hj-add="1">Tambah Harga Jasa</button></div></div>');
    try {
      state.hjList = await api("/api/harga-jasa");
      renderHargaJasaTable();
    } catch (e) {
      $("#hj-table").innerHTML = '<p class="error">' + escapeHtml(e.message) + "</p>";
    }
  }

  function renderHargaJasaTable() {
    const list = state.hjList || [];
    const q = (state.hjQuery || "").trim().toLowerCase();
    const filtered = list.filter(function (s) {
      if (!q) return true;
      return (s.nama || "").toLowerCase().indexOf(q) !== -1;
    });
    if (!filtered.length) {
      $("#hj-table").innerHTML = '<p class="muted">' + (list.length ? "Tidak ada jasa yang cocok." : "Belum ada harga jasa.") + "</p>";
      return;
    }
    const rows = filtered.map(function (s) {
      return "<tr>" +
        "<td>" + escapeHtml(s.nama) + "</td>" +
        "<td><strong>" + fmtMoney(s.keuntungan) + "</strong></td>" +
        '<td><button class="btn sm" data-hj-edit="' + s.id + '" data-nama="' + escapeHtml(s.nama) + '" data-untung="' + escapeHtml(s.keuntungan || "") + '">Ubah</button> ' +
        '<button class="btn sm danger" data-hj-delete="' + s.id + '">Hapus</button></td>' +
        "</tr>";
    }).join("");
    $("#hj-table").innerHTML = '<table class="table"><thead><tr><th>Nama Jasa</th><th>Keuntungan</th><th></th></tr></thead><tbody>' +
      rows + "</tbody></table>";
  }

  function startHargaJasaAdd(btn) {
    var row = btn.closest(".add-row");
    row.innerHTML =
      '<input type="text" data-hj-name placeholder="Nama jasa">' +
      '<input type="text" data-hj-untung placeholder="Keuntungan">' +
      '<button class="btn sm primary" data-hj-add-save="1">Simpan</button>' +
      '<button class="btn sm ghost" data-hj-add-cancel="1">Batal</button>';
    row.querySelector('[data-hj-name]').focus();
  }

  async function saveHargaJasaAdd(btn) {
    var row = btn.closest(".add-row");
    var nama = row.querySelector('[data-hj-name]').value.trim();
    var untung = row.querySelector('[data-hj-untung]').value.trim();
    if (!nama) { showError("Nama jasa wajib diisi."); return; }
    btn.disabled = true;
    try {
      await api("/api/harga-jasa", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nama: nama, keuntungan: untung }),
      });
      navigate("hargaJasa");
    } catch (e) {
      showError("Gagal menambah: " + e.message);
      navigate("hargaJasa");
    }
  }

  function editHargaJasa(btn) {
    var id = btn.getAttribute("data-hj-edit");
    var nama = btn.getAttribute("data-nama") || "";
    var untung = btn.getAttribute("data-untung") || "";
    showModal("Ubah harga jasa", [
      { key: "nama", value: nama, placeholder: "Nama jasa" },
      { key: "keuntungan", value: untung, placeholder: "Keuntungan" },
    ], "Simpan", false, function (v) {
      api("/api/harga-jasa/" + id, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nama: v.nama, keuntungan: v.keuntungan }),
      }).then(function () { navigate("hargaJasa"); })
        .catch(function (e) { showError("Gagal menyimpan: " + e.message); });
    });
  }

  function deleteHargaJasa(btn) {
    var id = btn.getAttribute("data-hj-delete");
    showModal("Hapus harga jasa ini?", [], "Ya, Hapus", true, function () {
      api("/api/harga-jasa/" + id, { method: "DELETE" }).then(function () {
        navigate("hargaJasa");
      }).catch(function (e) {
        showError("Gagal menghapus: " + e.message);
      });
    });
  }

  // ---------------------------------------------------------------------------
  // Incomplete vehicles
  // ---------------------------------------------------------------------------
  async function renderIncomplete() {
    setContent('<div class="panel">' + loading("Memuat...") + "</div>");
    try {
      const vehicles = await api("/api/vehicles/incomplete");
      const warranty = await api("/api/service-records/incomplete-warranty");
      const vRows = vehicles.map(function (v) {
        var reasons = (v.missing_fields || []).map(function (f) {
          return FIELD_LABELS[f] || f;
        }).join(", ");
        return '<div class="vcard">' +
          '<div class="vcard-plate">' + escapeHtml(v.nopol) + '</div>' +
          '<div class="vcard-line muted">Belum diisi: ' + escapeHtml(reasons) + '</div>' +
          '<div class="vcard-line"><button class="btn sm" data-open="' + v.id + '">Detail</button></div>' +
          '</div>';
      }).join("");
      const wRows = warranty.map(function (r) {
        return '<div class="vcard">' +
          '<div class="vcard-plate">' + escapeHtml(r.nopol) + '</div>' +
          '<div class="vcard-line muted">' + fmtDate(r.waktu_service) + '</div>' +
          '<div class="vcard-line"><button class="btn sm" data-warranty-edit="' + r.id + '" data-current="" data-bergaransi="">Isi Garansi</button></div>' +
          '</div>';
      }).join("");
      setContent(
        '<div class="panel"><h2>Data Belum Lengkap</h2>' +
        '<h3>Kendaraan</h3>' +
        (vRows ? '<div class="vcard-grid">' + vRows + '</div>' : '<p class="muted">Semua kendaraan lengkap.</p>') +
        '<h3>Garansi</h3>' +
        (wRows ? '<div class="vcard-grid">' + wRows + '</div>' : '<p class="muted">Semua garansi sudah diisi.</p>') +
        '</div>'
      );
    } catch (e) {
      setContent('<div class="panel"><p class="error">' + escapeHtml(e.message) + "</p></div>");
    }
  }

  // ---------------------------------------------------------------------------
  // Garansi (warranty management)
  // ---------------------------------------------------------------------------
  async function renderGaransi() {
    state.warrantyFilter = state.warrantyFilter || "all";
    setContent('<div class="panel">' + loading("Memuat data garansi...") + "</div>");
    try {
      state.warrantyList = await api("/api/service-records?limit=500");
      renderWarrantyView();
    } catch (e) {
      setContent('<div class="panel"><p class="error">' + escapeHtml(e.message) + "</p></div>");
    }
  }

  function filterDropdown(id, activeKey, options) {
    var html = '<select id="' + id + '">';
    options.forEach(function (opt) {
      var sel = (String(activeKey || "all") === String(opt.value)) ? " selected" : "";
      html += '<option value="' + escapeHtml(opt.value) + '"' + sel + '>' + escapeHtml(opt.label) + '</option>';
    });
    return html + '</select>';
  }

  function warrantyOptions() {
    return [
      { value: "all", label: "Semua" },
      { value: "on", label: "Garansi ON" },
      { value: "off", label: "OFF / Kadaluarsa" },
      { value: "none", label: "Tidak bergaransi" },
      { value: "empty", label: "Belum diisi" },
      { value: "claimed", label: "Sudah claim" },
      { value: "unclaimed", label: "Belum claim" },
    ];
  }

  function jasaOptions() {
    var opts = [{ value: "all", label: "Semua" }];
    (state.jasaList || []).forEach(function (j) {
      if (j && j.nama) opts.push({ value: j.nama, label: j.nama });
    });
    return opts;
  }

  function matchesWarrantyFilter(r, filter) {
    filter = filter || "all";
    var today = new Date();
    today.setHours(0, 0, 0, 0);
    if (filter === "on") {
      return r.bergaransi === true && r.garansi_sampai && new Date(r.garansi_sampai) >= today;
    }
    if (filter === "off") {
      return r.bergaransi === true && r.garansi_sampai && new Date(r.garansi_sampai) < today;
    }
    if (filter === "none") {
      return r.bergaransi === false;
    }
    if (filter === "empty") {
      return r.bergaransi == null;
    }
    if (filter === "claimed") {
      return r.status_klaim === "Sudah claim";
    }
    if (filter === "unclaimed") {
      return r.status_klaim === "Belum claim";
    }
    return true;
  }

  function matchesJasaFilter(r, filter) {
    filter = filter || "all";
    if (filter === "all") return true;
    return ((r.jasa || "").toLowerCase().indexOf(filter.toLowerCase()) !== -1);
  }

  function renderWarrantyView() {
    var list = state.warrantyList || [];
    var q = (state.warrantyQuery || "").trim().toLowerCase();
    var filter = state.warrantyFilter || "all";

    var filtered = list.filter(function (r) {
      if (!matchesWarrantyFilter(r, filter)) return false;
      if (q) {
        var hay = ((r.nopol || "") + " " + (r.nama_client || "")).toLowerCase();
        if (hay.indexOf(q) === -1) return false;
      }
      return true;
    });

    var filters = '<div class="toolbar">' + filterDropdown("garansi-filter", filter, warrantyOptions()) +
      '<input type="text" id="warranty-search" placeholder="Cari nama pemilik / plat..." value="' + escapeHtml(state.warrantyQuery || "") + '"></div>';

    var rows = filtered.map(function (r) {
      return '<div class="vcard" data-record="' + r.id + '">' +
        '<div class="vcard-top">' +
        '<div class="vcard-plate">' + escapeHtml(r.nopol) + '</div>' +
        '<span class="act-total">' + fmtDate(r.waktu_service) + '</span>' +
        '</div>' +
        '<div class="vcard-line"><strong>' + escapeHtml(r.nama_client || r.jasa || "—") + '</strong></div>' +
        '<div class="vcard-line">' + warrantyStatus(r) + '</div>' +
        '<div class="vcard-line">' + claimStatus(r) + '</div>' +
        '<div class="vcard-line">' +
        '<button class="btn sm" data-warranty-edit="' + r.id + '" data-current="' + escapeHtml(r.garansi_sampai || "") + '" data-bergaransi="' + (r.bergaransi == null ? "" : (r.bergaransi ? "1" : "0")) + '">Ubah Garansi</button> ' +
        '<button class="btn sm" data-claim-toggle="' + escapeHtml(r.status_klaim) + '" data-record-id="' + r.id + '">Ubah Status Klaim</button>' +
        '</div>' +
        '</div>';
    }).join("");

    setContent('<div class="panel"><h2>Garansi</h2>' + filters +
      (filtered.length ? '<div class="vcard-grid">' + rows + '</div>' : '<p class="muted">Tidak ada data garansi.</p>') +
      '</div>');
  }

  // ---------------------------------------------------------------------------
  // Vehicles list (search + pagination)
  // ---------------------------------------------------------------------------
  function renderVehicles() {
    setContent(
      '<div class="toolbar">' +
      '<input id="vehicle-search" type="text" placeholder="Cari nama atau plat nomor…" value="' + escapeHtml(state.vehicleQuery) + '">' +
      '<button id="vehicle-search-btn" class="btn primary">Cari</button>' +
      '<button id="vehicle-reset-btn" class="btn ghost">Reset</button>' +
      "</div>" +
      '<div class="panel"><h2>Daftar Kendaraan</h2><div id="vehicle-list">' + loading("Memuat…") + "</div></div>"
    );

    $("#vehicle-search-btn").addEventListener("click", function () {
      state.vehicleQuery = $("#vehicle-search").value.trim();
      state.vehiclePage = 0;
      loadVehicles();
    });
    $("#vehicle-search").addEventListener("keydown", function (e) {
      if (e.key === "Enter") { state.vehicleQuery = this.value.trim(); state.vehiclePage = 0; loadVehicles(); }
    });
    $("#vehicle-reset-btn").addEventListener("click", function () {
      state.vehicleQuery = "";
      state.vehiclePage = 0;
      $("#vehicle-search").value = "";
      loadVehicles();
    });

    loadVehicles();
  }

  async function loadVehicles() {
    const listEl = $("#vehicle-list");
    listEl.innerHTML = loading("Memuat…");

    try {
      let items;
      if (state.vehicleQuery) {
        items = await api("/api/vehicles/search?q=" + encodeURIComponent(state.vehicleQuery));
        listEl.innerHTML = vehicleTable(items);
        return;
      }

      items = await api("/api/vehicles?limit=500&offset=0");
      listEl.innerHTML = vehicleTable(items);
    } catch (e) {
      listEl.innerHTML = '<p class="error">' + escapeHtml(e.message) + "</p>";
    }
  }

  function vehicleTable(items) {
    if (!items.length) return '<p class="muted">Tidak ada kendaraan.</p>';
    return '<div class="vcard-grid">' +
      items.map(function (v) {
        const kendaraan = [v.jenis_mobil, v.tahun_mobil].filter(Boolean).join(" ");
        const contact = [v.nomor_wa, v.alamat_client].filter(Boolean).join(" · ");
        return '<div class="vcard" data-open="' + v.id + '">' +
          '<div class="vcard-top">' +
          '<div class="vcard-id"><strong>' + escapeHtml(display(v.nama_client)) + "</strong>" +
          '<div class="vcard-plate">' + escapeHtml(v.nopol) + "</div></div>" +
          '<button class="btn sm" data-open="' + v.id + '">Detail</button>' +
          "</div>" +
          (contact ? '<div class="vcard-line">' + escapeHtml(contact) + "</div>" : "") +
          (kendaraan ? '<div class="vcard-line muted">' + escapeHtml(kendaraan) + "</div>" : "") +
          "</div>";
      }).join("") +
      "</div>";
  }

  // ---------------------------------------------------------------------------
  // Vehicle detail
  // ---------------------------------------------------------------------------
  async function renderVehicleDetail() {
    const id = state.currentVehicleId;
    setContent('<div class="panel">' + loading("Memuat detail…") + "</div>");

    try {
      const v = await api("/api/vehicles/" + id);
      const records = await api("/api/vehicles/" + id + "/service-records");

      const complete = (v.missing_fields || []).length === 0;
      const badge = complete
        ? '<span class="badge ok">Data Lengkap</span>'
        : '<span class="badge warn">Belum Lengkap (' + v.missing_fields.length + " field)</span>";

      setContent(
        '<div class="panel">' +
        '<div class="toolbar">' +
        '<button class="btn ghost" data-back="vehicles">← Kembali</button>' +
        '<button class="btn primary" data-edit="' + v.id + '">Edit Kendaraan</button>' +
        "</div>" +
        '<div class="entity-head">' +
        "<h2 style=\"margin:0\">" + escapeHtml(display(v.nama_client)) + "</h2>" +
        '<div class="entity-plate">' + escapeHtml(v.nopol) + "</div>" +
        badge +
        "</div>" +
        '<div class="detail-grid">' +
        detailItem("Nomor WhatsApp", display(v.nomor_wa)) +
        detailItem("Jenis Mobil", display(v.jenis_mobil)) +
        detailItem("Tahun Mobil", display(v.tahun_mobil)) +
        detailItem("Alamat Client", display(v.alamat_client)) +
        detailItem("Jumlah Riwayat Servis", v.service_record_count) +
        "</div>" +
        "</div>" +
        '<section class="panel"><h2>Riwayat Servis</h2>' +
        '<div class="add-row"><button class="btn sm" data-record-add="1">Tambah Riwayat Servis</button></div>' +
        '<div id="records">' + recordsHtml(records) + "</div></section>"
      );
    } catch (e) {
      setContent('<div class="panel"><p class="error">' + escapeHtml(e.message) + "</p>" +
        '<button class="btn ghost" data-back="vehicles">← Kembali ke daftar</button></div>');
    }
  }

  function detailItem(key, value) {
    return '<div class="detail-item"><div class="k">' + escapeHtml(key) + "</div><div>" + escapeHtml(value) + "</div></div>";
  }

  function detailItemHtml(key, html) {
    return '<div class="detail-item"><div class="k">' + escapeHtml(key) + "</div><div>" + html + "</div></div>";
  }

  function fmtDateOnly(iso) {
    if (!iso) return "–";
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso));
    if (m) return m[3] + "-" + m[2] + "-" + m[1];
    return String(iso);
  }

  function recordsHtml(records) {
    if (!records.length) return '<p class="muted">Belum ada riwayat servis.</p>';
    return records.map(function (r) {
      const jobs = r.jobs || [];
      const parts = r.parts || [];
      let detail = "tanpa rincian";
      if (jobs.length) {
        const names = jobs.slice(0, 3).map(function (j) { return j.deskripsi; }).join(", ");
        detail = names + (jobs.length > 3 ? " (+" + (jobs.length - 3) + ")" : "");
        if (parts.length) detail += "; " + parts.length + " part";
      } else if (parts.length) {
        detail = parts.length + " part";
      }
      return '<div class="record">' +
        '<div class="record-head">' +
        "<strong>" + fmtDate(r.waktu_service) + "</strong>" +
        '<span class="record-total">' + fmtMoney(r.total_servis) + "</span>" +
        "</div>" +
        '<div class="muted">Status klaim: ' + escapeHtml(display(r.status_klaim)) +
        (r.garansi_sampai ? " · Garansi s/d: " + fmtDateOnly(r.garansi_sampai) : "") + "</div>" +
        '<div class="muted">' + escapeHtml(detail) + "</div>" +
        '<div class="record-actions"><button class="btn sm" data-record="' + r.id + '">Lihat Detail</button></div>' +
        "</div>";
    }).join("");
  }

  // ---------------------------------------------------------------------------
  // Service record detail (dedicated view)
  // ---------------------------------------------------------------------------
  async function renderServiceDetail() {
    const id = state.currentRecordId;
    setContent('<div class="panel">' + loading("Memuat detail servis…") + "</div>");

    let r, v;
    try {
      r = await api("/api/service-records/" + id);
      state.currentVehicleId = r.vehicle_id;  // ensure "back" returns to the right vehicle
      v = await api("/api/vehicles/" + r.vehicle_id);
    } catch (e) {
      setContent('<div class="panel"><p class="error">' + escapeHtml(e.message) + "</p>" +
        '<button class="btn ghost" data-back="vehicleDetail">← Kembali</button></div>');
      return;
    }

    setContent(
      '<div class="panel">' +
      '<div class="toolbar">' +
      '<button class="btn ghost" data-back="vehicleDetail">← Kembali ke Kendaraan</button>' +
      '<button class="btn ghost" data-claim-toggle="' + escapeHtml(r.status_klaim) + '" data-record-id="' + r.id + '">Ubah Status Klaim</button>' +
      '<button class="btn danger" data-record-delete="1">Hapus Servis</button>' +
      '</div>' +
      '<div class="entity-head">' +
      "<h2 style=\"margin:0\">" + escapeHtml(display(v.nama_client)) + "</h2>" +
      '<div class="entity-plate">' + escapeHtml(v.nopol) + "</div>" +
      "</div>" +
      '<div class="detail-grid">' +
      detailItem("Tanggal Servis", fmtDate(r.waktu_service)) +
      detailItem("Jenis Mobil", display(v.jenis_mobil)) +
      detailItem("Total Biaya", fmtMoney(r.total_servis)) +
      detailItemHtml("Garansi", warrantyStatus(r)) +
      detailItemHtml("Status Klaim", claimStatus(r)) +
      detailItem("Catatan", r.catatan || "Belum tersedia") +
      "</div>" +
      "</div>" +
      '<section class="panel"><h2>Rincian Pekerjaan Jasa</h2>' + jobsTable(r.jobs) + "</section>" +
      '<section class="panel"><h2>Rincian Suku Cadang</h2>' + partsTable(r.parts) + "</section>" +
      '<section class="panel"><h2>Ringkasan Biaya</h2>' + costSummary(r) + "</section>"
    );
  }

  function jobsTable(jobs) {
    var addBtn = '<div class="add-row"><button class="btn sm" data-job-add="1">Tambah Pekerjaan</button></div>';
    if (!jobs || !jobs.length) {
      return '<p class="muted">Belum ada rincian pekerjaan.</p>' + addBtn;
    }
    return '<table class="table"><thead><tr><th>Nama Pekerjaan</th><th>Kuantitas</th><th>Harga Satuan</th><th>Subtotal</th></tr></thead><tbody>' +
      jobs.map(function (j) {
        return "<tr><td>" + escapeHtml(j.deskripsi) + "</td><td>" + escapeHtml(j.jumlah) +
          '</td><td class="price-cell"><span class="price-display">' + fmtMoney(j.harga) + '</span><button class="btn sm" data-job-edit="' + j.id + '" data-value="' + escapeHtml(j.harga || "") + '">Ubah</button></td>' +
          "<td>" + fmtMoney(j.subtotal) + "</td></tr>";
      }).join("") + "</tbody></table>" + addBtn;
  }

  function partsTable(parts) {
    var addBtn = '<div class="add-row"><button class="btn sm" data-part-add="1">Tambah Suku Cadang</button></div>';
    if (!parts || !parts.length) {
      return '<p class="muted">Belum ada rincian suku cadang.</p>' + addBtn;
    }
    return '<table class="table"><thead><tr><th>Nama Suku Cadang</th><th>Kuantitas</th><th>Harga Satuan</th><th>Subtotal</th></tr></thead><tbody>' +
      parts.map(function (p) {
        return "<tr><td>" + escapeHtml(p.nama_part) + "</td><td>" + escapeHtml(p.jumlah) +
          '</td><td class="price-cell"><span class="price-display">' + fmtMoney(p.harga_satuan) + '</span><button class="btn sm" data-part-edit="' + p.id + '" data-value="' + escapeHtml(p.harga_satuan || "") + '">Ubah</button></td>' +
          "<td>" + fmtMoney(p.subtotal) + "</td></tr>";
      }).join("") + "</tbody></table>" + addBtn;
  }

  function costSummary(r) {
    const na = "Belum tersedia";
    const hasJobs = (r.jobs || []).length > 0;
    const hasParts = (r.parts || []).length > 0;
    const jasaValue = hasJobs ? (r.biaya_jasa != null ? fmtMoney(r.biaya_jasa) : na) : na;
    const partValue = hasParts ? (r.total_part != null ? fmtMoney(r.total_part) : na) : na;
    return '<table class="table"><tbody>' +
      '<tr><td>Subtotal Jasa</td><td class="ta-r"><strong>' + jasaValue + "</strong></td></tr>" +
      '<tr><td>Subtotal Suku Cadang</td><td class="ta-r"><strong>' + partValue + "</strong></td></tr>" +
      '<tr><td>Total</td><td class="ta-r"><strong>' + (r.total_servis != null ? fmtMoney(r.total_servis) : na) + "</strong></td></tr>" +
      "</tbody></table>";
  }

  function startJobPriceEdit(btn) {
    const id = btn.getAttribute("data-job-edit");
    const current = btn.getAttribute("data-value") || "";
    const cell = btn.closest(".price-cell");
    cell.innerHTML =
      '<input class="price-input" type="text" value="' + escapeHtml(current) + '" placeholder="0"><button class="btn sm primary" data-job-save="' + id + '">Simpan</button><button class="btn sm ghost" data-job-cancel="' + id + '">Batal</button>';
    cell.querySelector(".price-input").focus();
  }

  function startPartPriceEdit(btn) {
    const id = btn.getAttribute("data-part-edit");
    const current = btn.getAttribute("data-value") || "";
    const cell = btn.closest(".price-cell");
    cell.innerHTML =
      '<input class="price-input" type="text" value="' + escapeHtml(current) + '" placeholder="0"><button class="btn sm primary" data-part-save="' + id + '">Simpan</button><button class="btn sm ghost" data-part-cancel="' + id + '">Batal</button>';
    cell.querySelector(".price-input").focus();
  }

  async function saveJobPrice(btn) {
    const id = btn.getAttribute("data-job-save");
    const cell = btn.closest(".price-cell");
    const value = cell.querySelector(".price-input").value;
    btn.disabled = true;
    try {
      await api("/api/service-jobs/" + id, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ harga: value }),
      });
      navigate("serviceDetail");
    } catch (e) {
      showError("Gagal menyimpan harga: " + e.message);
      navigate("serviceDetail");
    }
  }

  async function savePartPrice(btn) {
    const id = btn.getAttribute("data-part-save");
    const cell = btn.closest(".price-cell");
    const value = cell.querySelector(".price-input").value;
    btn.disabled = true;
    try {
      await api("/api/service-parts/" + id, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ harga_satuan: value }),
      });
      navigate("serviceDetail");
    } catch (e) {
      showError("Gagal menyimpan harga: " + e.message);
      navigate("serviceDetail");
    }
  }

  function startJobAdd(btn) {
    var row = btn.closest(".add-row");
    row.innerHTML =
      '<input type="text" data-add-name placeholder="Nama pekerjaan">' +
      '<input type="number" data-add-qty value="1" min="1" style="width:70px">' +
      '<input type="text" data-add-price placeholder="Harga (opsional)">' +
      '<button class="btn sm primary" data-job-add-save="1">Simpan</button>' +
      '<button class="btn sm ghost" data-job-add-cancel="1">Batal</button>';
    row.querySelector('[data-add-name]').focus();
  }

  async function startPartAdd(btn) {
    var row = btn.closest(".add-row");
    var opts = '<option value="">— Tanpa stok —</option>';
    try {
      const stock = await api("/api/stock");
      opts += stock.map(function (s) {
        return '<option value="' + s.id + '">' + escapeHtml(s.nama) + (s.kode ? " (" + escapeHtml(s.kode) + ")" : "") + " · stok " + escapeHtml(s.jumlah) + "</option>";
      }).join("");
    } catch (e) {}
    row.innerHTML =
      '<select data-add-stock>' + opts + "</select>" +
      '<input type="text" data-add-name placeholder="Nama part">' +
      '<input type="number" data-add-qty value="1" min="1" style="width:70px">' +
      '<input type="text" data-add-price placeholder="Harga jual (opsional)">' +
      '<button class="btn sm primary" data-part-add-save="1">Simpan</button>' +
      '<button class="btn sm ghost" data-part-add-cancel="1">Batal</button>';
    row.querySelector('[data-add-name]').focus();
  }

  async function saveJobAdd(btn) {
    var row = btn.closest(".add-row");
    var name = row.querySelector('[data-add-name]').value.trim();
    var qty = parseInt(row.querySelector('[data-add-qty]').value, 10) || 1;
    var price = row.querySelector('[data-add-price]').value.trim();
    if (!name) { showError("Nama pekerjaan wajib diisi."); return; }
    btn.disabled = true;
    try {
      await api("/api/service-records/" + state.currentRecordId + "/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ deskripsi: name, jumlah: qty, harga: price }),
      });
      navigate("serviceDetail");
    } catch (e) {
      showError("Gagal menambah pekerjaan: " + e.message);
      navigate("serviceDetail");
    }
  }

  async function savePartAdd(btn) {
    var row = btn.closest(".add-row");
    var stockId = row.querySelector('[data-add-stock]').value;
    var name = row.querySelector('[data-add-name]').value.trim();
    var qty = parseInt(row.querySelector('[data-add-qty]').value, 10) || 1;
    var price = row.querySelector('[data-add-price]').value.trim();
    if (!name) { showError("Nama suku cadang wajib diisi."); return; }
    btn.disabled = true;
    try {
      await api("/api/service-records/" + state.currentRecordId + "/parts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nama_part: name, jumlah: qty, harga_satuan: price, stock_item_id: stockId ? parseInt(stockId, 10) : null }),
      });
      navigate("serviceDetail");
    } catch (e) {
      showError("Gagal menambah suku cadang: " + e.message);
      navigate("serviceDetail");
    }
  }

  function startRecordAdd(btn) {
    var row = btn.closest(".add-row");
    row.innerHTML =
      '<input type="date" data-add-date title="Tanggal servis">' +
      '<select data-add-bergaransi title="Garansi">' +
      '<option value="">Pilih garansi</option>' +
      '<option value="1">Bergaransi</option>' +
      '<option value="0">Tidak bergaransi</option>' +
      '</select>' +
      '<input type="date" data-add-garansi title="Garansi s/d">' +
      '<input type="text" data-add-total placeholder="Total (opsional)">' +
      '<input type="text" data-add-catatan placeholder="Catatan (opsional)">' +
      '<button class="btn sm primary" data-record-add-save="1">Simpan</button>' +
      '<button class="btn sm ghost" data-record-add-cancel="1">Batal</button>';
    row.querySelector('[data-add-date]').focus();
  }

  async function saveRecordAdd(btn) {
    var row = btn.closest(".add-row");
    var date = row.querySelector('[data-add-date]').value;
    var bSel = row.querySelector('[data-add-bergaransi]').value;
    var garansi = row.querySelector('[data-add-garansi]').value;
    var total = row.querySelector('[data-add-total]').value.trim();
    var catatan = row.querySelector('[data-add-catatan]').value.trim();
    var bergaransi = (bSel === "1") ? true : (bSel === "0" ? false : null);
    btn.disabled = true;
    try {
      await api("/api/vehicles/" + state.currentVehicleId + "/service-records", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          waktu_service: date || null,
          bergaransi: bergaransi,
          garansi_sampai: garansi || null,
          total_servis: total || null,
          catatan: catatan || null,
        }),
      });
      render();
    } catch (e) {
      showError("Gagal menambah riwayat: " + e.message);
      render();
    }
  }

  function toggleClaim(btn) {
    var current = btn.getAttribute("data-claim-toggle");
    var recordId = btn.getAttribute("data-record-id") || state.currentRecordId;

    if (current !== "Sudah claim") {
      showModal("Apakah benar ingin merubah jadi sudah klaim?", [], "Ya", false, function () {
        showModal("Tanggal claim garansi (YYYY-MM-DD / DD-MM-YYYY / hari ini / 2 Agustus 2026):",
          [{ key: "tanggal", placeholder: "YYYY-MM-DD" }],
          "Simpan", false, function (v) {
            var val = (v.tanggal || "").trim();
            api("/api/service-records/" + recordId + "/claim", {
              method: "PUT",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ status_klaim: "Sudah claim", tanggal_klaim: val || null }),
            }).then(function () { render(); })
              .catch(function (e) { showError("Gagal mengubah status: " + e.message); });
          });
      });
      return;
    }

    showModal("Kembalikan status jadi belum claim?", [], "Ya", false, function () {
      api("/api/service-records/" + recordId + "/claim", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status_klaim: "Belum claim", tanggal_klaim: null }),
      }).then(function () { render(); })
        .catch(function (e) { showError("Gagal mengubah status: " + e.message); });
    });
  }

  function deleteRecord(btn) {
    showModal("Hapus riwayat servis ini? Tindakan tidak bisa dibatalkan.", [], "Ya, Hapus", true, function () {
      api("/api/service-records/" + state.currentRecordId, { method: "DELETE" }).then(function () {
        navigate("vehicleDetail");
      }).catch(function (e) {
        showError("Gagal menghapus: " + e.message);
      });
    });
  }

  function deleteVehicle(btn) {
    showModal("Hapus kendaraan ini?", [], "Ya, Hapus", true, function () {
      api("/api/vehicles/" + state.currentVehicleId, { method: "DELETE" }).then(function () {
        navigate("vehicles");
      }).catch(function (e) {
        showError("Gagal menghapus: " + e.message);
      });
    });
  }

  // ---------------------------------------------------------------------------
  // Vehicle edit
  // ---------------------------------------------------------------------------
  async function renderVehicleEdit() {
    const id = state.currentVehicleId;
    setContent('<div class="panel">' + loading("Memuat data kendaraan…") + "</div>");

    let v;
    try {
      v = await api("/api/vehicles/" + id);
    } catch (e) {
      setContent('<div class="panel"><p class="error">' + escapeHtml(e.message) + "</p>" +
        '<button class="btn ghost" data-back="detail">← Kembali</button></div>');
      return;
    }

    const fields = [
      { key: "nama_client", label: "Nama Client" },
      { key: "nomor_wa", label: "Nomor WhatsApp" },
      { key: "nopol", label: "Plat Nomor" },
      { key: "jenis_mobil", label: "Jenis Mobil" },
      { key: "tahun_mobil", label: "Tahun Mobil", type: "number" },
      { key: "alamat_client", label: "Alamat Client" },
    ];

    const inputs = fields.map(function (f) {
      const val = v[f.key] === null || v[f.key] === undefined ? "" : String(v[f.key]);
      return '<div class="form-field"><label>' + escapeHtml(f.label) + "</label>" +
        '<input id="edit-' + f.key + '" type="' + (f.type || "text") + '" value="' + escapeHtml(val) + '"></div>';
    }).join("");

    setContent(
      '<div class="panel">' +
      '<div class="toolbar"><button class="btn ghost" data-back="detail">← Kembali</button></div>' +
      "<h2>Edit Kendaraan — " + escapeHtml(v.nopol) + "</h2>" +
      '<p class="muted">Hanya field yang Anda ubah yang akan dikirim (update parsial).</p>' +
      '<form id="edit-form" class="form-grid">' + inputs + "</form>" +
      '<div class="form-actions">' +
      '<button id="edit-save" class="btn primary">Simpan</button>' +
      '<button class="btn ghost" data-back="detail">Batal</button>' +
      '<button class="btn danger" data-vehicle-delete="1">Hapus Kendaraan</button>' +
      "</div>" +
      '<p id="edit-msg" class="hidden"></p>' +
      "</div>"
    );

    $("#edit-save").addEventListener("click", function () { saveEdit(v); });
    $("#edit-form").addEventListener("submit", function (e) {
      e.preventDefault();
      saveEdit(v);
    });
  }

  async function saveEdit(original) {
    const fields = ["nama_client", "nomor_wa", "nopol", "jenis_mobil", "tahun_mobil", "alamat_client"];
    const payload = {};
    for (const key of fields) {
      const raw = $("#edit-" + key).value;
      let newVal;
      if (raw === "") {
        if (key === "nopol") continue; // plat tidak boleh dikosongkan
        newVal = null;
      } else if (key === "tahun_mobil") {
        const n = parseInt(raw, 10);
        if (isNaN(n)) {
          showEditMsg("Tahun mobil harus berupa angka.", "error");
          return; // abort save
        }
        newVal = n;
      } else {
        newVal = raw;
      }
      const origVal = original[key] === null || original[key] === undefined ? null : original[key];
      if (newVal !== origVal) payload[key] = newVal;
    }

    const keys = Object.keys(payload);
    if (!keys.length) {
      showEditMsg("Tidak ada perubahan.", "muted");
      return;
    }

    const msgEl = $("#edit-msg");
    msgEl.className = "muted";
    msgEl.textContent = "Menyimpan…";
    msgEl.classList.remove("hidden");
    $("#edit-save").disabled = true;

    try {
      await api("/api/vehicles/" + state.currentVehicleId, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      state.view = "vehicleDetail";
      render();
    } catch (e) {
      if (e.status === 409) showEditMsg("Plat nomor sudah terdaftar pada kendaraan lain.", "error");
      else if (e.status === 422) showEditMsg("Input tidak valid: " + e.message, "error");
      else if (e.status === 400) showEditMsg("Permintaan tidak valid: " + e.message, "error");
      else showEditMsg(e.message, "error");
      $("#edit-save").disabled = false;
    }
  }

  function showEditMsg(text, cls) {
    const el = $("#edit-msg");
    el.textContent = text;
    el.className = cls;
    el.classList.remove("hidden");
  }

  // ---------------------------------------------------------------------------
  // Backup & Restore
  // ---------------------------------------------------------------------------
  function fmtBytes(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(2) + " MB";
  }

  function fmtBackupTimestamp(ts) {
    if (!ts) return "–";
    const m = /^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})_/.exec(ts);
    if (!m) return ts;
    return m[3] + "-" + m[2] + "-" + m[1] + " " + m[4] + ":" + m[5] + ":" + m[6];
  }

  function renderBackup() {
    setContent(
      '<section class="panel"><h2>Backup Database</h2>' +
      '<p class="muted">Membuat salinan database SQLite ke folder backup.</p>' +
      '<div class="backup-actions"><button id="backup-btn" class="btn primary">Buat Backup</button>' +
      '<span id="backup-status"></span></div>' +
      '<div id="backup-result" class="backup-result hidden"></div></section>' +
      '<section class="panel"><h2>Restore Database</h2>' +
      '<div class="warn-box">⚠️ Restore akan mengganti database aktif dengan isi file backup. ' +
      "Hentikan bot Telegram terlebih dahulu untuk mengurangi risiko konflik akses SQLite lintas proses.</div>" +
      '<p class="muted">Pilih file backup (maks. 50 MB), lalu konfirmasi untuk mengganti database.</p>' +
      '<div class="backup-actions">' +
      '<input type="file" id="restore-file" accept=".db,.sqlite,.sqlite3">' +
      '<button id="restore-btn" class="btn danger" disabled>Restore…</button>' +
      "</div>" +
      '<p id="restore-msg" class="hidden"></p></section>'
    );

    $("#backup-btn").addEventListener("click", doBackup);
    $("#restore-file").addEventListener("change", function () {
      $("#restore-btn").disabled = !this.files.length;
    });
    $("#restore-btn").addEventListener("click", doRestore);
  }

  async function doBackup() {
    const btn = $("#backup-btn");
    const statusEl = $("#backup-status");
    const result = $("#backup-result");
    btn.disabled = true;
    statusEl.innerHTML = loading("Membuat backup…");
    result.classList.add("hidden");
    try {
      const meta = await api("/api/admin/backup", { method: "POST" });
      statusEl.textContent = "";
      result.classList.remove("hidden");
      result.innerHTML = "Berhasil. File: <strong>" + escapeHtml(meta.filename) + "</strong>" +
        " · Ukuran: " + fmtBytes(meta.size) +
        " · Dibuat: " + fmtBackupTimestamp(meta.created_at);
    } catch (e) {
      statusEl.textContent = "";
      result.classList.remove("hidden");
      result.innerHTML = '<p class="error">' + escapeHtml(e.message) + "</p>";
    } finally {
      btn.disabled = false;
    }
  }

  function doRestore() {
    const file = $("#restore-file").files[0];
    if (!file) return;
    if (file.size > 50 * 1024 * 1024) {
      showRestoreMsg("File terlalu besar (maks. 50 MB).", "error");
      return;
    }
    showModal("Restore akan MENGGANTI database aktif dengan isi file: " + file.name, [], "Ya, Restore", true, function () {
      performRestore(file);
    });
  }

  async function performRestore(file) {
    const btn = $("#restore-btn");
    btn.disabled = true;
    showRestoreMsg("Mengirim file dan melakukan restore…", "muted");
    try {
      const buf = await file.arrayBuffer();
      await api("/api/admin/restore", {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: buf,
      });
      showRestoreMsg("Restore berhasil. Database aktif telah diganti.", "success");
    } catch (e) {
      showRestoreMsg("Restore gagal: " + e.message, "error");
    } finally {
      btn.disabled = false;
      $("#restore-file").value = "";
      $("#restore-btn").disabled = true;
    }
  }

  function showRestoreMsg(text, cls) {
    const el = $("#restore-msg");
    el.textContent = text;
    el.className = cls;
    el.classList.remove("hidden");
  }

  // ---------------------------------------------------------------------------
  // Event delegation & boot
  // ---------------------------------------------------------------------------
  $("#content").addEventListener("click", function (e) {
    const jobEditBtn = e.target.closest("[data-job-edit]");
    if (jobEditBtn) { startJobPriceEdit(jobEditBtn); return; }
    const jobSaveBtn = e.target.closest("[data-job-save]");
    if (jobSaveBtn) { saveJobPrice(jobSaveBtn); return; }
    const jobCancelBtn = e.target.closest("[data-job-cancel]");
    if (jobCancelBtn) { navigate("serviceDetail"); return; }
    const partEditBtn = e.target.closest("[data-part-edit]");
    if (partEditBtn) { startPartPriceEdit(partEditBtn); return; }
    const partSaveBtn = e.target.closest("[data-part-save]");
    if (partSaveBtn) { savePartPrice(partSaveBtn); return; }
    const partCancelBtn = e.target.closest("[data-part-cancel]");
    if (partCancelBtn) { navigate("serviceDetail"); return; }
    const jobAddBtn = e.target.closest("[data-job-add]");
    if (jobAddBtn) { startJobAdd(jobAddBtn); return; }
    const jobAddSaveBtn = e.target.closest("[data-job-add-save]");
    if (jobAddSaveBtn) { saveJobAdd(jobAddSaveBtn); return; }
    const jobAddCancelBtn = e.target.closest("[data-job-add-cancel]");
    if (jobAddCancelBtn) { navigate("serviceDetail"); return; }
    const partAddBtn = e.target.closest("[data-part-add]");
    if (partAddBtn) { startPartAdd(partAddBtn); return; }
    const partAddSaveBtn = e.target.closest("[data-part-add-save]");
    if (partAddSaveBtn) { savePartAdd(partAddSaveBtn); return; }
    const partAddCancelBtn = e.target.closest("[data-part-add-cancel]");
    if (partAddCancelBtn) { navigate("serviceDetail"); return; }
    const recordAddBtn = e.target.closest("[data-record-add]");
    if (recordAddBtn) { startRecordAdd(recordAddBtn); return; }
    const recordAddSaveBtn = e.target.closest("[data-record-add-save]");
    if (recordAddSaveBtn) { saveRecordAdd(recordAddSaveBtn); return; }
    const recordAddCancelBtn = e.target.closest("[data-record-add-cancel]");
    if (recordAddCancelBtn) { navigate("vehicleDetail"); return; }
    const claimToggleBtn = e.target.closest("[data-claim-toggle]");
    if (claimToggleBtn) { toggleClaim(claimToggleBtn); return; }
    const recordDeleteBtn = e.target.closest("[data-record-delete]");
    if (recordDeleteBtn) { deleteRecord(recordDeleteBtn); return; }
    const vehicleDeleteBtn = e.target.closest("[data-vehicle-delete]");
    if (vehicleDeleteBtn) { deleteVehicle(vehicleDeleteBtn); return; }
    const stockAddBtn = e.target.closest("[data-stock-add]");
    if (stockAddBtn) { startStockAdd(stockAddBtn); return; }
    const stockAddSaveBtn = e.target.closest("[data-stock-add-save]");
    if (stockAddSaveBtn) { saveStockAdd(stockAddSaveBtn); return; }
    const stockAddCancelBtn = e.target.closest("[data-stock-add-cancel]");
    if (stockAddCancelBtn) { navigate("stock"); return; }
    const stockEditBtn = e.target.closest("[data-stock-edit]");
    if (stockEditBtn) { editStock(stockEditBtn); return; }
    const stockDeleteBtn = e.target.closest("[data-stock-delete]");
    if (stockDeleteBtn) { deleteStock(stockDeleteBtn); return; }
    const warrantyEditBtn = e.target.closest("[data-warranty-edit]");
    if (warrantyEditBtn) { editWarranty(warrantyEditBtn); return; }
    const profitCard = e.target.closest("[data-profit]");
    if (profitCard) { renderProfitHistory(profitCard.dataset.profit); return; }
    const hjAddBtn = e.target.closest("[data-hj-add]");
    if (hjAddBtn) { startHargaJasaAdd(hjAddBtn); return; }
    const hjAddSaveBtn = e.target.closest("[data-hj-add-save]");
    if (hjAddSaveBtn) { saveHargaJasaAdd(hjAddSaveBtn); return; }
    const hjAddCancelBtn = e.target.closest("[data-hj-add-cancel]");
    if (hjAddCancelBtn) { navigate("hargaJasa"); return; }
    const hjEditBtn = e.target.closest("[data-hj-edit]");
    if (hjEditBtn) { editHargaJasa(hjEditBtn); return; }
    const hjDeleteBtn = e.target.closest("[data-hj-delete]");
    if (hjDeleteBtn) { deleteHargaJasa(hjDeleteBtn); return; }
    const openBtn = e.target.closest("[data-open]");
    if (openBtn) {
      state.currentVehicleId = parseInt(openBtn.dataset.open, 10);
      navigate("vehicleDetail");
      return;
    }
    const recBtn = e.target.closest("[data-record]");
    if (recBtn) {
      state.currentRecordId = parseInt(recBtn.dataset.record, 10);
      navigate("serviceDetail");
      return;
    }
    const navBtn = e.target.closest("[data-nav]");
    if (navBtn) {
      navigate(navBtn.dataset.nav);
      return;
    }
    const editBtn = e.target.closest("[data-edit]");
    if (editBtn) {
      state.currentVehicleId = parseInt(editBtn.dataset.edit, 10);
      navigate("vehicleEdit");
      return;
    }
    const backBtn = e.target.closest("[data-back]");
    if (backBtn) {
      navigate(backBtn.dataset.back);
      return;
    }
  });

  $("#content").addEventListener("change", function (e) {
    if (e.target && e.target.id === "profit-period") {
      loadProfit();
    }
    if (e.target && e.target.id === "garansi-filter") {
      state.warrantyFilter = e.target.value;
      renderWarrantyView();
    }
    if (e.target && e.target.id === "service-filter") {
      state.serviceFilter = e.target.value;
      renderServiceView();
    }
  });

  $("#content").addEventListener("input", function (e) {
    if (e.target && e.target.id === "services-search") {
      state.serviceQuery = e.target.value;
      renderServiceView();
    }
    if (e.target && e.target.id === "warranty-search") {
      state.warrantyQuery = e.target.value;
      renderWarrantyView();
    }
    if (e.target && e.target.id === "stock-search") {
      state.stockQuery = e.target.value;
      renderStockTable();
    }
    if (e.target && e.target.id === "hj-search") {
      state.hjQuery = e.target.value;
      renderHargaJasaTable();
    }
  });

  $("#modal-cancel").addEventListener("click", hideModal);
  $("#modal-ok").addEventListener("click", function () {
    var values = {};
    $("#modal-fields").querySelectorAll("input, select").forEach(function (inp) {
      values[inp.dataset.key] = inp.value;
    });
    var cb = _modalCallback;
    hideModal();
    if (cb) cb(values);
  });

  document.querySelectorAll(".nav-item").forEach(function (b) {
    b.addEventListener("click", function () { navigate(b.dataset.view); });
  });

  $("#login-form").addEventListener("submit", function (e) {
    e.preventDefault();
    const token = $("#token-input").value.trim();
    if (!token) { showLogin("Masukkan token terlebih dahulu."); return; }
    sessionStorage.setItem(TOKEN_KEY, token);
    state.token = token;
    showApp();
    navigate("dashboard");
  });

  $("#logout-btn").addEventListener("click", logout);

  function waStatusLabel(s) { if (s === "DISETUJUI") return "Disetujui"; if (s === "DITOLAK") return "Ditolak"; return "Menunggu Review"; }
  function waStatusBadge(s) { var cls = s === "DISETUJUI" ? "ok" : s === "DITOLAK" ? "danger" : "warn"; return '<span class="badge ' + cls + '">' + waStatusLabel(s) + '</span>'; }
  function waArrivalLabel(s) { if (s === "MENUNGGU_KEDATANGAN") return "Menunggu Kedatangan"; if (s === "DIJADWALKAN") return "Dijadwalkan"; if (s === "DATANG") return "Datang"; if (s === "TIDAK_DATANG") return "Tidak Datang"; return "—"; }
  function waArrivalBadge(s) { if (!s || s === "KOSONG") return '<span class="badge off">—</span>'; var cls = s === "DATANG" ? "ok" : s === "TIDAK_DATANG" ? "danger" : "on"; return '<span class="badge ' + cls + '">' + waArrivalLabel(s) + '</span>'; }
  function waNotice(connected) { if (connected) return ""; return '<div class="wa-notice">⚠️ Gateway WhatsApp belum terhubung. Data berasal dari backend lokal.</div>'; }
  function waKv(label, value) { var shown = (value == null || value === "") ? '<span class="muted">Belum diisi</span>' : escapeHtml(value); return '<div class="kv"><span class="k">' + escapeHtml(label) + '</span><span class="v">' + shown + '</span></div>'; }
  function waContactRow(k) {
    var name = k.nama || k.wa_number;
    var sub = (k.plat ? k.plat + " · " : "") + (k.issue_summary || "Belum ada keluhan");
    return '<div class="act-item clickable" data-wa-open="' + k.id + '">' +
      '<div class="act-main"><div class="act-plate">' + escapeHtml(name) + '</div>' +
      '<div class="act-name">' + escapeHtml(sub) + '</div></div>' +
      '<div class="act-side">' + waStatusBadge(k.registration_status) + ' ' + waArrivalBadge(k.arrival_status) +
      '<span class="muted" style="font-size:12px">' + escapeHtml(k.last_contact_at ? fmtDate(k.last_contact_at) : "") + '</span></div></div>';
  }

  var waPollTimer = null;
  var waPollView = null;
  function stopWaPoll() {
    if (waPollTimer) { clearInterval(waPollTimer); waPollTimer = null; }
    waPollView = null;
  }
  function startWaPoll(view) {
    stopWaPoll();
    waPollView = view;
    waPollTimer = setInterval(waPollTick, 5000);
  }
  async function waPollTick() {
    if (!waPollView || state.view !== waPollView) { stopWaPoll(); return; }
    try {
      var gw = await api("/api/wa/gateway/status");
      if (!gw.connected) return;
      if (waPollView === "waCs") { renderWaCs(true); }
      else if (waPollView === "waInbox") { await refreshWaInbox(); }
      else if (waPollView === "waConversation") { await refreshWaConversation(); }
    } catch (e) { /* abaikan error polling */ }
  }
  function waBubble(m) {
    var cls = "wa-bubble " + (m.sender === "customer" ? "customer" : m.sender === "owner" ? "owner" : "ai");
    var label = m.sender === "customer" ? "Pelanggan" : m.sender === "owner" ? "Owner" : "AI";
    return '<div class="' + cls + '"><div>' + escapeHtml(m.body) + '</div><div class="wa-msg-meta">' + escapeHtml(label + " · " + (m.created_at ? fmtDate(m.created_at) : "")) + '</div></div>';
  }
  function waIsTakenOver(k) {
    if (!k.owner_takeover_on) return false;
    var t = new Date();
    var mm = String(t.getMonth() + 1).padStart(2, "0");
    var dd = String(t.getDate()).padStart(2, "0");
    return k.owner_takeover_on === (t.getFullYear() + "-" + mm + "-" + dd);
  }
  async function refreshWaInbox() {
    try {
      var contacts = await api("/api/wa/contacts");
      var questions = await api("/api/wa/questions");
      state.waContacts = contacts;
      state.waQuestions = questions;
      renderWaInboxList();
    } catch (e) { /* abaikan */ }
  }
  async function refreshWaConversation() {
    var id = state.currentWaId;
    try {
      var d = await api("/api/wa/contacts/" + id);
      var count = (d.messages || []).length;
      if (count !== state.waMsgCount) {
        state.waMsgCount = count;
        var thread = document.querySelector(".wa-thread");
        if (thread) {
          var html = "";
          (d.messages || []).forEach(function (m) { html += waBubble(m); });
          thread.innerHTML = html;
          thread.scrollTop = thread.scrollHeight;
        }
      }
      var side = document.querySelector(".wa-side");
      if (side) { side.innerHTML = waSidePanel(d.contact, d.candidates, d.questions); }
    } catch (e) { /* abaikan */ }
  }
  async function waSendReply() {
    var input = $("#wa-reply-input");
    if (!input || !input.value.trim()) return;
    var text = input.value.trim();
    var id = state.currentWaId;
    try {
      await api("/api/wa/contacts/" + id + "/reply", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: text }) });
      input.value = "";
      state.waMsgCount = null;
      await refreshWaConversation();
    } catch (e) { showModal(e.message, [], "OK", false, null, true); }
  }

  async function renderWaCs(silent) {
    if (!silent) setContent('<div class="panel">' + loading("Memuat WhatsApp CS...") + '</div>');
    try {
      var contacts = await api("/api/wa/contacts");
      var candidates = await api("/api/wa/candidates");
      var questions = await api("/api/wa/questions");
      var gw = await api("/api/wa/gateway/status");
      var review = candidates.filter(function (c) { return c.status === "MENUNGGU_REVIEW"; }).length;
      var approved = contacts.filter(function (c) { return c.registration_status === "DISETUJUI"; }).length;
      var rejected = contacts.filter(function (c) { return c.registration_status === "DITOLAK"; }).length;
      var waiting = contacts.filter(function (c) { return c.arrival_status === "MENUNGGU_KEDATANGAN" || c.arrival_status === "DIJADWALKAN"; }).length;
      var openQ = questions.filter(function (q) { return q.status === "MENUNGGU"; }).length;
      var html = waNotice(gw.connected) + '<div class="cards">' +
        '<div class="card clickable" data-wa-card="MENUNGGU_REVIEW"><div class="card-label">Kandidat Menunggu Review</div><div class="card-value">' + review + '</div></div>' +
        '<div class="card clickable" data-wa-card="DISETUJUI"><div class="card-label">Disetujui</div><div class="card-value">' + approved + '</div></div>' +
        '<div class="card clickable" data-wa-card="DITOLAK"><div class="card-label">Ditolak</div><div class="card-value">' + rejected + '</div></div>' +
        '<div class="card clickable" data-wa-card="ARRIVAL"><div class="card-label">Menunggu / Dijadwalkan</div><div class="card-value">' + waiting + '</div></div>' +
        '<div class="card clickable" data-wa-card="QUESTIONS"><div class="card-label">Pertanyaan Owner</div><div class="card-value">' + openQ + '</div></div>' +
        '</div>';
      html += '<section class="panel"><h2>Kontak Terbaru</h2>' +
        '<div class="toolbar"><button class="btn primary" data-wa-card="">Buka Inbox</button>' +
        '</div><div class="act-list">';
      contacts.slice(0, 5).forEach(function (k) { html += waContactRow(k); });
      html += '</div></section>';
      setContent(html);
      if (!silent) startWaPoll("waCs");
    } catch (e) { setContent('<div class="panel"><p class="error">' + escapeHtml(e.message) + '</p></div>'); }
  }

  async function renderWaInbox() {
    setContent('<div class="panel">' + loading("Memuat inbox...") + '</div>');
    try {
      var contacts = await api("/api/wa/contacts");
      var questions = await api("/api/wa/questions");
      state.waContacts = contacts;
      state.waQuestions = questions;
      var html = '<div class="panel"><h2>Inbox WhatsApp</h2>' +
        '<div class="toolbar"><input type="text" id="wa-search" placeholder="Cari nomor / nama / plat..." value="' + escapeHtml(state.waQuery || "") + '">' +
        '<select id="wa-status-filter"><option value="">Semua Status</option><option value="MENUNGGU_REVIEW">Menunggu Review</option><option value="DISETUJUI">Disetujui</option><option value="DITOLAK">Ditolak</option><option value="ARRIVAL">Menunggu / Dijadwalkan</option><option value="QUESTIONS">Ada Pertanyaan Owner</option></select>' +
        '<button class="btn ghost" data-nav="waCs">← Dashboard</button></div>' +
        '<div id="wa-inbox-list"></div></div>';
      setContent(html);
      var sel = $("#wa-status-filter");
      if (sel) sel.value = state.waFilter || "";
      renderWaInboxList();
      startWaPoll("waInbox");
    } catch (e) { setContent('<div class="panel"><p class="error">' + escapeHtml(e.message) + '</p></div>'); }
  }

  function renderWaInboxList() {
    var el = $("#wa-inbox-list"); if (!el) return;
    var q = (state.waQuery || "").trim().toLowerCase();
    var filter = state.waFilter || "";
    var openQIds = {};
    if (filter === "QUESTIONS") {
      (state.waQuestions || []).forEach(function (qq) { if (qq.status === "MENUNGGU") openQIds[qq.contact_id] = true; });
    }
    var list = (state.waContacts || []).filter(function (k) {
      if (q && ((k.wa_number || "") + " " + (k.nama || "") + " " + (k.plat || "")).toLowerCase().indexOf(q) === -1) return false;
      if (filter === "ARRIVAL") { return k.arrival_status === "MENUNGGU_KEDATANGAN" || k.arrival_status === "DIJADWALKAN"; }
      if (filter === "QUESTIONS") { return !!openQIds[k.id]; }
      if (filter && k.registration_status !== filter) return false;
      return true;
    });
    if (!list.length) { el.innerHTML = '<div class="muted">Tidak ada kontak.</div>'; return; }
    var html = '<div class="act-list">';
    list.forEach(function (k) { html += waContactRow(k); });
    el.innerHTML = html + '</div>';
  }

  function waSidePanel(k, candidates, questions) {
    var html = '<h2>Profil &amp; Konteks</h2>';
    html += '<div class="side-block"><h3>Identitas</h3>' + waKv("Nama", k.nama) + waKv("WhatsApp", k.wa_number) + waKv("Plat", k.plat) + waKv("Jenis", k.jenis_mobil) + waKv("Tahun", k.tahun_mobil) + '</div>';
    html += '<div class="side-block"><h3>Keluhan</h3><div>' + escapeHtml(k.issue_summary || "—") + '</div></div>';
    html += '<div class="side-block"><h3>Memori</h3><div class="muted">' + escapeHtml(k.context_summary || "—") + '</div></div>';
    html += '<div class="side-block"><h3>Status</h3>' +
      '<div class="kv"><span class="k">Pendaftaran</span><span class="v">' + waStatusBadge(k.registration_status) + '</span></div>' +
      '<div class="kv"><span class="k">Kedatangan</span><span class="v">' + waArrivalBadge(k.arrival_status) + '</span></div>' +
      '<div class="kv"><span class="k">Delay</span><span class="v">' + escapeHtml(String(k.delay_seconds)) + ' detik</span></div>' +
      (waIsTakenOver(k) ? '<div class="kv"><span class="k">Penanganan</span><span class="v"><span class="badge warn">Dipegang owner hari ini</span></span></div>' : '') +
      '</div>';
    var pending = (candidates || []).filter(function (c) { return c.status === "MENUNGGU_REVIEW"; });
    if (pending.length) {
      html += '<div class="side-block"><h3>Kandidat Kendaraan</h3>';
      pending.forEach(function (c) {
        html += '<div><div class="muted">' + escapeHtml(c.nopol || "tanpa plat") + ' · ' + escapeHtml(c.nama || "-") + '</div>' +
          '<div class="actions"><button class="btn primary sm" data-wa-approve="' + c.id + '">ACC</button>' +
          '<button class="btn danger sm" data-wa-reject="' + c.id + '">Tolak</button></div></div>';
      });
      html += '</div>';
    }
    var openQs = (questions || []).filter(function (q) { return q.status === "MENUNGGU"; });
    if (openQs.length) {
      html += '<div class="side-block"><h3>Pertanyaan Owner</h3>';
      openQs.forEach(function (q) {
        html += '<div style="margin-bottom:6px">' + escapeHtml(q.pesan) + (q.alasan ? ' <span class="muted">(' + escapeHtml(q.alasan) + ')</span>' : '') + '</div>';
      });
      html += '<div class="muted">Balas lewat kotak pesan di bawah; jawaban otomatis menutup pertanyaan ini.</div></div>';
    }
    html += '<div class="side-block"><h3>Hak Akses Agent</h3><div class="wa-access-note">WhatsApp CS hanya membaca data yang diizinkan dan membalas pesan. ACC/Tolak di sini dilakukan owner melalui UI (bukan oleh AI WhatsApp).</div></div>';
    return html;
  }

  async function renderWaConversation() {
    var id = state.currentWaId;
    setContent('<div class="panel">' + loading("Memuat percakapan...") + '</div>');
    try {
      var d = await api("/api/wa/contacts/" + id);
      var k = d.contact;
      var gw = await api("/api/wa/gateway/status");
      state.waMsgCount = (d.messages || []).length;
      var html = waNotice(gw.connected) +
        '<div class="toolbar"><button class="btn ghost" data-back="waInbox">← Kembali ke Inbox</button></div>' +
        '<div class="wa-layout">' +
        '<section class="panel"><div class="entity-head"><div><div style="font-weight:700;font-size:16px">' + escapeHtml(k.nama || k.wa_number) + '</div>' +
        '<div class="muted">' + escapeHtml(k.wa_number) + (waIsTakenOver(k) ? ' · <span class="badge warn">Dipegang owner hari ini</span>' : '') + '</div></div></div>' +
        '<div class="wa-thread">';
      (d.messages || []).forEach(function (m) { html += waBubble(m); });
      html += '</div>' +
        '<div class="wa-reply"><input type="text" id="wa-reply-input" placeholder="Balas ke pelanggan..."><button class="btn primary" data-wa-reply-send>Kirim</button></div>' +
        '</section>' +
        '<aside class="panel wa-side">' + waSidePanel(k, d.candidates, d.questions) + '</aside>' +
        '</div>';
      setContent(html);
      startWaPoll("waConversation");
    } catch (e) { setContent('<div class="panel"><p class="error">' + escapeHtml(e.message) + '</p></div>'); }
  }

  async function waApprove(id) {
    try {
      await api("/api/wa/candidates/" + id + "/approve", { method: "POST" });
      renderWaConversation();
      showModal("Kandidat disetujui dan kendaraan ditautkan ke database utama (tanpa servis/stok/keuangan).", [], "OK", false, null, true);
    } catch (e) { showModal(e.message, [], "OK", false, null, true); }
  }
  async function waReject(id) {
    try {
      await api("/api/wa/candidates/" + id + "/reject", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ alasan: "ditolak owner" }) });
      renderWaConversation();
      showModal("Kandidat ditolak (kontak tetap tersimpan).", [], "OK", false, null, true);
    } catch (e) { showModal(e.message, [], "OK", false, null, true); }
  }
  async function waSaveSettings() {
    var body = {
      nama_bengkel: $("#wa-cfg-name").value,
      alamat: $("#wa-cfg-address").value,
      jam_operasional: $("#wa-cfg-hours").value,
      maps_link: $("#wa-cfg-maps").value,
      agent_prompt: $("#wa-cfg-prompt").value,
      default_delay_seconds: parseInt($("#wa-cfg-delay").value || "60", 10),
    };
    try {
      await api("/api/wa/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      showModal("Pengaturan tersimpan.", [], "OK", false, null, true);
    } catch (e) { showModal(e.message, [], "OK", false, null, true); }
  }

  $("#content").addEventListener("click", function (e) {
    var open = e.target.closest("[data-wa-open]");
    if (open) { state.currentWaId = parseInt(open.dataset.waOpen, 10); navigate("waConversation"); return; }
    var card = e.target.closest("[data-wa-card]");
    if (card) { state.waFilter = card.dataset.waCard; state.waQuery = ""; navigate("waInbox"); return; }
    var approve = e.target.closest("[data-wa-approve]");
    if (approve) { waApprove(parseInt(approve.dataset.waApprove, 10)); return; }
    var reject = e.target.closest("[data-wa-reject]");
    if (reject) { waReject(parseInt(reject.dataset.waReject, 10)); return; }
    var save = e.target.closest("[data-wa-save-settings]");
    if (save) { waSaveSettings(); return; }
    var reply = e.target.closest("[data-wa-reply-send]");
    if (reply) { waSendReply(); return; }
  });
  $("#content").addEventListener("input", function (e) {
    if (e.target && e.target.id === "wa-search") { state.waQuery = e.target.value; renderWaInboxList(); }
  });
  $("#content").addEventListener("change", function (e) {
    if (e.target && e.target.id === "wa-status-filter") { state.waFilter = e.target.value; renderWaInboxList(); }
  });

  function waStatusText(s) {
    var m = {disconnected: "Terputus", connecting: "Menghubungkan", awaiting_scan: "Menunggu scan QR", awaiting_pairing: "Menunggu kode pairing", connected: "Terhubung", reconnecting: "Menghubungkan ulang", logged_out: "Logout", error: "Error", bridge_unavailable: "Gateway tidak berjalan"};
    return m[s] || (s || "—");
  }
  function waCfgBadge(ok, okText, badText) { return ok ? '<span class="badge ok">' + okText + '</span>' : '<span class="badge off">' + badText + '</span>'; }
  function waSecretRow(id, key, label, status) {
    return '<div class="form-field"><label>' + label + '</label>' +
      '<input type="password" id="' + id + '" placeholder="Kosongkan = tidak mengubah">' +
      '<div class="wa-hint">' + (status.stored ? ('Tersimpan: ' + escapeHtml(status.masked)) : 'Belum disimpan') + (status.active ? ' (aktif)' : '') + (status.needs_restart ? ' — perlu restart' : '') + '</div>' +
      '<div class="toolbar" style="margin-top:8px"><button class="btn primary sm" data-ai-save="' + key + '">Simpan</button>' +
      '<button class="btn ghost sm" data-ai-test="' + key + '">Uji Koneksi</button>' +
      '<button class="btn danger sm" data-ai-delete="' + key + '">Hapus</button></div></div>';
  }

  async function renderIntegrations() {
    setContent('<div class="panel">' + loading("Memuat pengaturan integrasi...") + '</div>');
    try {
      var st = await api("/api/integrations/status");
      var ag = await api("/api/wa/settings");
      var wa = st.whatsapp || {};
      var html = '<section class="panel"><h2>WhatsApp — Baileys</h2>' +
        '<div class="detail-grid">' +
        '<div class="detail-item"><div class="k">Status</div><div>' + waCfgBadge(wa.status === "connected", "Terhubung", waStatusText(wa.status)) + '</div></div>' +
        '<div class="detail-item"><div class="k">Nomor Terautentikasi</div><div>' + escapeHtml(wa.authedNumber || "—") + '</div></div>' +
        '</div>' +
        '<div class="toolbar"><button class="btn primary" data-wa-qr>Mulai Scan QR</button>' +
        '<button class="btn ghost" data-wa-logout>Logout</button></div>' +
        '<div class="form-grid" style="margin-top:12px"><div class="form-field"><label>Kode Pairing — Nomor WhatsApp</label>' +
        '<input type="text" id="wa-pair-phone" placeholder="Contoh: 62812xxxxxxxx">' +
        '<button class="btn primary sm" data-wa-pairing style="margin-top:8px">Minta Kode Pairing</button></div></div>' +
        '<div id="wa-qr-box"></div><div id="wa-pair-box"></div>' +
        '<p class="muted" style="margin-top:12px">Jalankan proses gateway dengan: <code>node gateway/whatsapp_bridge.js</code></p>' +
        '</section>';
      html += '<section class="panel"><h2>Telegram — Bot Token</h2>' +
        '<div class="form-field"><label>Bot Token</label><input type="password" id="tg-token" placeholder="Kosongkan = tidak mengubah">' +
        '<div class="wa-hint">' + (st.providers.telegram.stored ? ('Tersimpan: ' + escapeHtml(st.providers.telegram.masked)) : 'Belum disimpan') + (st.providers.telegram.needs_restart ? ' — perlu restart bot' : '') + '</div>' +
        '<div class="toolbar" style="margin-top:8px"><button class="btn primary sm" data-tg-save>Simpan</button>' +
        '<button class="btn ghost sm" data-tg-test>Uji Koneksi</button>' +
        '<button class="btn danger sm" data-tg-delete>Hapus</button></div></div>' +
        '<p class="muted">Uji memakai getMe Telegram. Token tidak pernah dikirim balik ke UI.</p></section>';
      html += '<section class="panel"><h2>AI Provider</h2><div class="form-grid">' +
        waSecretRow("ds-key", "deepseek_api_key", "DeepSeek API Key", st.providers.deepseek) +
        waSecretRow("gm-key", "gemini_api_key", "Gemini API Key (opsional, vision/OCR)", st.providers.gemini) +
        '</div><p class="muted">API key tidak pernah dikirim balik ke UI; hanya status tersamarkan.</p></section>';
      html += '<section class="panel"><h2>Agent WhatsApp CS</h2>' +
        '<div class="form-grid">' +
        '<div class="form-field"><label>Nama Bengkel</label><input type="text" id="wa-cfg-name" value="' + escapeHtml(ag.nama_bengkel || "") + '"></div>' +
        '<div class="form-field"><label>Jam Operasional</label><input type="text" id="wa-cfg-hours" value="' + escapeHtml(ag.jam_operasional || "") + '"></div>' +
        '</div>' +
        '<div class="form-grid">' +
        '<div class="form-field"><label>Alamat Lengkap</label><input type="text" id="wa-cfg-address" value="' + escapeHtml(ag.alamat || "") + '"></div>' +
        '<div class="form-field"><label>Link Google Maps</label><input type="text" id="wa-cfg-maps" value="' + escapeHtml(ag.maps_link || "") + '"></div>' +
        '</div>' +
        '<div class="form-grid">' +
        '<div class="form-field"><label>Prompt / Instruksi AI</label><textarea class="wa-textarea" id="wa-cfg-prompt" rows="4">' + escapeHtml(ag.agent_prompt || "") + '</textarea></div>' +
        '<div class="form-field"><label>Delay Balasan per Nomor (detik)</label><input type="number" id="wa-cfg-delay" min="0" step="1" value="' + escapeHtml(String(ag.default_delay_seconds)) + '"><div class="wa-hint">Contoh: 60 detik.</div></div>' +
        '</div>' +
        '<div class="form-actions"><button class="btn primary" data-wa-save-settings>Simpan</button></div>' +
        '</section>' +
        '<section class="panel"><h2>Kebijakan Akses Agent</h2><ul class="wa-policy">' +
        '<li class="ok">Boleh: membaca data yang secara eksplisit diizinkan.</li>' +
        '<li class="no">Dilarang: membaca data keuangan internal dan data pelanggan lain.</li>' +
        '<li class="no">Dilarang: INSERT/UPDATE/DELETE pada database operasional via WhatsApp.</li>' +
        '<li class="no">Tidak ada toggle yang membuka hak tulis database utama.</li>' +
        '</ul></section>';
      setContent(html);
    } catch (e) { setContent('<div class="panel"><p class="error">' + escapeHtml(e.message) + '</p></div>'); }
  }

  async function waIntegrationAction(method, url, body) {
    var opt = { method: method };
    if (body !== undefined) { opt.headers = { "Content-Type": "application/json" }; opt.body = JSON.stringify(body); }
    return await api(url, opt);
  }

  $("#content").addEventListener("click", function (e) {
    var qr = e.target.closest("[data-wa-qr]");
    if (qr) {
      waIntegrationAction("POST", "/api/integrations/whatsapp/qr/start").then(function () { return waPollQr(); });
      return;
    }
    var pair = e.target.closest("[data-wa-pairing]");
    if (pair) {
      var phone = $("#wa-pair-phone").value.trim();
      var box = $("#wa-pair-box");
      if (!phone) { box.innerHTML = '<p class="error">Isi nomor WhatsApp dulu (contoh: 62812xxxxxxxx).</p>'; return; }
      box.innerHTML = loading("Meminta kode pairing...");
      waIntegrationAction("POST", "/api/integrations/whatsapp/pairing/request", { phone: phone }).then(function (r) {
        if (r.pairingCode) {
          box.innerHTML = '<div class="wa-notice">Kode pairing Anda: <strong style="font-size:22px;letter-spacing:3px">' + escapeHtml(r.pairingCode) + '</strong></div>' +
            '<ol style="margin:10px 0 0 18px;line-height:1.7">' +
            '<li>Buka WhatsApp di HP Anda.</li>' +
            '<li>Setelan (⋮) → Perangkat Tertaut → Tautkan Perangkat.</li>' +
            '<li>Pilih <strong>Tautkan dengan nomor telepon</strong>.</li>' +
            '<li>Ketik kode di atas — kode TIDAK dikirim otomatis ke HP.</li>' +
            '</ol>' +
            '<p class="muted">Kode kedaluwarsa cepat (±2 menit). Jika gagal/tertutup, klik ulang "Minta Kode Pairing".</p>';
        } else if (r.error) { box.innerHTML = '<p class="error">' + escapeHtml(r.error) + '</p>'; }
        else { box.innerHTML = '<p class="error">Tidak ada respons kode dari gateway.</p>'; }
      }).catch(function (er) { box.innerHTML = '<p class="error">' + escapeHtml(er.message) + '</p>'; });
      return;
    }
    var logout = e.target.closest("[data-wa-logout]");
    if (logout) { waIntegrationAction("POST", "/api/integrations/whatsapp/logout").then(function () { renderIntegrations(); }); return; }
    var tgSave = e.target.closest("[data-tg-save]");
    if (tgSave) { var t = $("#tg-token").value; if (!t) { showModal("Isi token terlebih dahulu.", [], "OK", false, null, true); return; } waIntegrationAction("POST", "/api/integrations/telegram/save", { token: t }).then(function (r) { showModal("Token valid & tersimpan (username: " + (r.username || "-") + "). Perlu restart bot untuk aktif.", [], "OK", false, null, true); }).catch(function (er) { showModal(er.message, [], "OK", false, null, true); }); return; }
    var tgTest = e.target.closest("[data-tg-test]");
    if (tgTest) { var t2 = $("#tg-token").value; if (!t2) { showModal("Isi token untuk diuji.", [], "OK", false, null, true); return; } waIntegrationAction("POST", "/api/integrations/telegram/test", { token: t2 }).then(function (r) { showModal(r.valid ? ("Valid — bot: " + (r.username || r.name || "-")) : ("Tidak valid: " + (r.error || "")), [], "OK", false, null, true); }); return; }
    var tgDel = e.target.closest("[data-tg-delete]");
    if (tgDel) { waIntegrationAction("POST", "/api/integrations/telegram/delete").then(function () { renderIntegrations(); }); return; }
    var aiSave = e.target.closest("[data-ai-save]");
    if (aiSave) { var k = aiSave.dataset.aiSave; var id = (k === "deepseek_api_key") ? "#ds-key" : "#gm-key"; var v = $(id).value; if (!v) { showModal("Isi API key terlebih dahulu.", [], "OK", false, null, true); return; } waIntegrationAction("POST", "/api/integrations/" + (k === "deepseek_api_key" ? "deepseek" : "gemini") + "/save", { value: v }).then(function () { showModal("Tersimpan (perlu restart untuk aktif).", [], "OK", false, null, true); renderIntegrations(); }); return; }
    var aiTest = e.target.closest("[data-ai-test]");
    if (aiTest) { var k2 = aiTest.dataset.aiTest; var id2 = (k2 === "deepseek_api_key") ? "#ds-key" : "#gm-key"; var v2 = $(id2).value; if (!v2) { showModal("Isi API key untuk diuji.", [], "OK", false, null, true); return; } waIntegrationAction("POST", "/api/integrations/" + (k2 === "deepseek_api_key" ? "deepseek" : "gemini") + "/test", { value: v2 }).then(function (r) { showModal(r.valid ? "Koneksi valid." : ("Gagal: " + (r.error || "")), [], "OK", false, null, true); }); return; }
    var aiDel = e.target.closest("[data-ai-delete]");
    if (aiDel) { var k3 = aiDel.dataset.aiDelete; waIntegrationAction("POST", "/api/integrations/" + (k3 === "deepseek_api_key" ? "deepseek" : "gemini") + "/delete").then(function () { renderIntegrations(); }); return; }
  });

  var waQrPollId = 0;
  async function waPollQr() {
    var myId = ++waQrPollId;
    var lastQr = null;
    var deadline = Date.now() + 5 * 60 * 1000; // maksimal 5 menit
    while (Date.now() < deadline) {
      if (myId !== waQrPollId) return;
      await new Promise(function (r) { setTimeout(r, 2000); });
      if (myId !== waQrPollId) return;
      var box = $("#wa-qr-box");
      if (!box) return;
      var st;
      try { st = await api("/api/integrations/whatsapp/status"); }
      catch (e) { box.innerHTML = '<p class="error">' + escapeHtml(e.message) + '</p>'; return; }
      if (myId !== waQrPollId) return;
      if (st.status === "connected") {
        box.innerHTML = '<div class="success">Terhubung' + (st.authedNumber ? ' sebagai ' + escapeHtml(st.authedNumber) : '') + '.</div>';
        renderIntegrations();
        return;
      }
      if (st.status === "error" || st.status === "logged_out" || st.status === "bridge_unavailable") {
        box.innerHTML = '<p class="error">' + escapeHtml(waStatusText(st.status)) + (st.error ? ' — ' + escapeHtml(st.error) : '') + '</p>';
        return;
      }
      if (st.qr && st.qr !== lastQr) {
        lastQr = st.qr;
        var secs = Math.max(0, Math.round((st.qrExpiresAt - Date.now()) / 1000));
        box.innerHTML = '<img src="' + st.qr + '" alt="QR" style="width:230px;height:230px">' +
          '<div class="muted">Pindai QR dengan WhatsApp. QR kedaluwarsa dalam ±' + secs + ' dtk, lalu diperbarui otomatis.</div>';
      }
    }
    var b2 = $("#wa-qr-box");
    if (b2) b2.innerHTML = '<p class="error">Waktu tunggu habis. Klik "Mulai Scan QR" lagi.</p>';
  }

  if (state.token) {
    showApp();
    navigate("dashboard");
  } else {
    showLogin();
  }
})();





