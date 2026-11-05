"""PDF panel; no file contents are stored in browser storage."""

HTML = '''
  <section class="ocr" id="pdf-panel">
    <h2>Isi dari PDF (AI)</h2>
    <p class="hint">Satu PDF, maksimal 20 halaman / 30 MB. Semua halaman diproses
    otomatis berurutan, satu panggilan AI per halaman (dapat berbayar dan memakan
    beberapa menit). Pilih jenis dokumen, bukan setiap halaman. PDF campuran:
    proses ulang dengan kategori lain bila diperlukan. Hasil bukan verifikasi hukum.</p>
    <label for="pdf-category">Jenis dokumen</label>
    <select id="pdf-category"><option value="identity">Identitas / KTP (pilih orang setelah hasil)</option>
    <option value="shm">Sertipikat / SHM dan Surat Ukur</option>
    <option value="akad">Akad / Perjanjian Kredit</option></select>
    <label for="pdf-file">Berkas PDF</label><input type="file" id="pdf-file" accept="application/pdf,.pdf">
    <p id="pdf-status" role="status" aria-live="polite">Pilih PDF untuk menghitung halaman secara lokal.</p>
    <p id="pdf-provider" class="hint"></p>
    <label><input type="checkbox" id="pdf-consent"> Saya setuju semua gambar halaman PDF
    ini dikirim ke penyedia AI melalui router untuk permintaan ini. Dokumen mungkin berisi data pribadi.</label>
    <div class="actions"><button type="button" id="pdf-run" disabled>Proses semua halaman</button>
    <button type="button" id="pdf-stop" class="secondary" disabled>Hentikan setelah halaman ini</button></div>
    <p class="hint">PDF/gambar sementara dihapus setelah permintaan selesai. Hasil tetap di memori
    halaman ini sampai ditutup/dibersihkan; hanya tersimpan bila Anda menyimpan draf sendiri.</p>
    <div id="pdf-results" hidden>
      <h3>Hasil PDF — nilai dan sumber halaman</h3>
      <p class="hint">Konflik tidak dipilih otomatis. Pilih nilai yang benar atau lewati.
      Identitas orang tidak digabung antarhalaman; pilih satu rekaman dan tujuan secara eksplisit.
      Setelah mengisi formulir, hasil dan tombol tetap tersedia. Pilih rekaman/tujuan lain
      lalu isi lagi tanpa memproses PDF ulang.</p>
      <p id="pdf-summary" role="status"></p>
      <ul id="pdf-pages"></ul>
      <div id="pdf-person-controls" hidden>
        <label for="pdf-person">Rekaman identitas</label><select id="pdf-person"></select>
        <label for="pdf-role">Isi identitas sebagai</label><select id="pdf-role">
          <option value="">Pilih tujuan…</option><option value="owner">Pemilik</option>
          <option value="spouse">Pasangan</option><option value="debtor">Debitor</option></select>
      </div>
      <div id="pdf-values"></div>
      <label><input type="checkbox" id="pdf-overwrite"> Izinkan timpa kolom terisi (akan dikonfirmasi)</label>
      <div class="actions"><button type="button" id="pdf-apply" disabled>Isi nilai terpilih ke formulir</button>
      <button type="button" id="pdf-clear" class="secondary">Bersihkan PDF dan hasil</button></div>
      <p id="pdf-applied" role="status" aria-live="polite"></p>
    </div>
  </section>
'''

JS = r'''
  var pdf = {data: null, count: 0, busy: false, stop: false, records: [], pages: [], errors: [], category: '', version: 0};
  function pe(id){ return document.getElementById('pdf-' + id); }
  function pdfStatus(text){ pe('status').textContent = text; }
  function pdfReady(){ pe('run').disabled = pdf.busy || !pdf.data || !pe('consent').checked; }
  async function pdfRequest(path, body){
    var res = await fetch('/api/pdf/' + path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    var j = await res.json();
    if(!res.ok || !j.ok){ throw new Error(j.error || 'PDF gagal diproses.'); }
    return j;
  }
  pe('file').addEventListener('change', async function(){
    var version = ++pdf.version;
    pdf.data = null; pdf.count = 0; pdf.records = []; pe('results').hidden = true; pe('apply').disabled = true;
    pe('consent').checked = false; pdfReady();
    var file = pe('file').files[0]; if(!file){ return; }
    if(file.size > 30*1024*1024){ pdfStatus('PDF melebihi 30 MB.'); return; }
    pdfStatus('Menghitung halaman lokal; belum dikirim ke AI…');
    try{
      var encoded = await new Promise(function(resolve,reject){
        var reader = new FileReader(); reader.onload = function(){ resolve(reader.result.split(',')[1]); };
        reader.onerror = function(){ reject(new Error('Berkas tidak terbaca.')); }; reader.readAsDataURL(file);
      });
      if(version !== pdf.version){ return; }
      var info = await pdfRequest('inspect', {pdf_base64:encoded});
      if(version !== pdf.version){ return; }
      pdf.data = encoded; pdf.count = info.page_count;
      pdfStatus(info.page_count + ' halaman; ' + info.page_count + ' panggilan AI. Centang persetujuan lalu proses.');
    }catch(e){ if(version === pdf.version){ pdfStatus(e.message); } }
    pdfReady();
  });
  pe('consent').addEventListener('change', pdfReady);
  pe('category').addEventListener('change', function(){ pe('consent').checked = false; pdfReady(); });
  pe('stop').addEventListener('click', function(){ pdf.stop = true; pdfStatus('Menghentikan setelah permintaan berjalan selesai; biaya halaman berjalan tetap berlaku.'); });
  pe('run').addEventListener('click', async function(){
    if(pdf.busy || !pdf.data || !pe('consent').checked){ return; }
    pdf.busy = true; pdf.stop = false; pdf.records = []; pdf.pages = []; pdf.errors = []; pdf.category = pe('category').value;
    pe('apply').disabled = true;
    pe('consent').checked = false; pe('results').hidden = true; pe('stop').disabled = false;
    pe('file').disabled = true; pe('category').disabled = true; pe('consent').disabled = true; pdfReady();
    var completed = 0;
    try{
      for(var p=1; p<=pdf.count && !pdf.stop; p++){
        pdfStatus('Memproses halaman ' + p + '/' + pdf.count + '…');
        var result = await pdfRequest('page', {pdf_base64:pdf.data, page:p, category:pdf.category, consent:true});
        if(!Array.isArray(result.records) || result.records.some(function(r){
          return !r || !r.fields || typeof r.fields !== 'object' || Array.isArray(r.fields);
        })){ throw new Error('Balasan halaman bukan records yang sah.'); }
        var keys = pdf.category === 'identity' ? pdfIdentityKeys : (pdf.category === 'shm' ? pdfLandKeys : pdfAkadKeys);
        var usable = result.records.filter(function(r){ return keys.some(function(k){ return typeof r.fields[k] === 'string' && r.fields[k].trim(); }); });
        usable.forEach(function(record){ pdf.records.push({page:p, fields:record.fields}); });
        pdf.pages.push({page:p, count:usable.length, diagnostics:result.diagnostics});
        completed++;
      }
      pdfStatus((pdf.stop ? 'Dihentikan. ' : 'Pemrosesan selesai. ') + completed + '/' + pdf.count + ' halaman diproses; ' + pdf.records.length + ' rekaman dapat digunakan. Periksa ringkasan hasil.');
    }catch(e){ pdf.errors.push({page:p, message:e.message}); pdfStatus('Halaman ' + p + ': ' + e.message + ' Hasil parsial: ' + completed + '/' + pdf.count + ' halaman. Tidak ada retry otomatis.'); }
    finally{
      pdf.busy = false; pe('stop').disabled = true; pe('file').disabled = false;
      pe('category').disabled = false; pe('consent').disabled = false; pdfReady(); pdfShow();
    }
  });
  function pdfShow(){
    pe('applied').textContent = '';
    pe('results').hidden = false; pe('overwrite').checked = false;
    var identity = pdf.category === 'identity'; pe('person-controls').hidden = !identity;
    pe('summary').textContent = pdf.pages.length + '/' + pdf.count + ' halaman diproses; ' + pdf.pages.filter(function(p){ return !p.count; }).length + ' halaman kosong; ' + pdf.errors.length + ' halaman gagal. ' +
      (!pdf.records.length ? (identity ? 'Tidak ada identitas yang dapat digunakan. ' : 'Tidak ada nilai yang dapat digunakan. ') + 'Periksa kategori/keterbacaan PDF atau isi manual. Penyebab hasil AI kosong belum diketahui.' : pdf.records.length + ' rekaman tersedia; periksa sebelum digunakan.');
    pe('pages').replaceChildren();
    pdf.pages.forEach(function(p){
      var li = document.createElement('li'), d = p.diagnostics;
      li.textContent = 'Halaman ' + p.page + ': ' + p.count + ' rekaman dapat digunakan' + (!p.count ? ' (kosong)' : '') + '.';
      if(d && ['provider_record_count','normalized_record_count','recognized_field_count'].every(function(k){ return Number.isInteger(d[k]) && d[k]>=0; })){
        li.textContent += ' Rekaman AI: ' + d.provider_record_count + '; hasil normalisasi: ' + d.normalized_record_count + '; kolom dikenali (teks valid sebelum normalisasi): ' + d.recognized_field_count + '.';
        if(d.reason === 'empty_model'){ li.textContent += ' AI mengembalikan daftar rekaman kosong (empty_model).'; }
        if(d.reason === 'no_usable_fields'){ li.textContent += ' Rekaman AI tidak menghasilkan kolom yang dapat digunakan (no_usable_fields).'; }
      }
      pe('pages').appendChild(li);
    });
    pdf.errors.forEach(function(e){ var li = document.createElement('li'); li.textContent = 'Halaman ' + e.page + ' gagal: ' + e.message; pe('pages').appendChild(li); });
    pe('person').disabled = !pdf.records.length;
    pe('person').replaceChildren(); pe('role').value = '';
    var blank = document.createElement('option'); blank.value = ''; blank.textContent = 'Pilih rekaman…'; pe('person').appendChild(blank);
    pdf.records.forEach(function(record,i){
      var op = document.createElement('option'); op.value = String(i);
      op.textContent = 'Halaman ' + record.page + ' — ' + (record.fields.nama || 'Identitas tanpa nama') + ' (rekaman ' + (i+1) + ')';
      pe('person').appendChild(op);
    });
    pdfValues();
  }
  var pdfIdentityKeys = ['nama','lahir_tempat','lahir_tanggal','pekerjaan','dusun','rt','rw','desa','kecamatan','kabupaten','nik'];
  var pdfLandKeys = ['ht_nomor','ht_desa_sertifikat','surat_ukur_nomor','surat_ukur_tanggal','luas_m2','nib','lok_desa','lok_kecamatan','lok_kabupaten','lok_provinsi'];
  var pdfAkadKeys = ['akad_jenis','akad_nomor','akad_tanggal','nilai_pembiayaan','nilai_tanggungan'];
  function pdfValues(){
    var box = pe('values'); box.replaceChildren(); var records = pdf.records;
    var keys = pdf.category === 'identity' ? pdfIdentityKeys : (pdf.category === 'shm' ? pdfLandKeys : pdfAkadKeys);
    if(pdf.category === 'identity'){
      records = pe('person').value === '' ? [] : [pdf.records[Number(pe('person').value)]].filter(Boolean);
    }
    keys.forEach(function(key){
      var choices = new Map();
      records.forEach(function(r){
        var value = r.fields[key]; if(typeof value !== 'string' || !value.trim()){ return; }
        if(!choices.has(value)){ choices.set(value,[]); } choices.get(value).push(r.page);
      });
      if(!choices.size){ return; }
      var label = document.createElement('label'); label.textContent = key + (choices.size>1 ? ' — KONFLIK: pilih eksplisit' : '');
      var select = document.createElement('select'); select.dataset.key = key; select.setAttribute('aria-label',key);
      var skip = document.createElement('option'); skip.value = ''; skip.textContent = 'Lewati'; select.appendChild(skip);
      choices.forEach(function(pages,value){
        var op = document.createElement('option'); op.value = value; op.dataset.pages = pages.join(', ');
        op.textContent = value + ' — hal. ' + pages.join(', '); select.appendChild(op);
      });
      if(choices.size === 1){ select.selectedIndex = 1; }
      label.appendChild(select); box.appendChild(label);
    });
    if(!box.children.length){ box.textContent = 'Belum ada nilai; pilih rekaman identitas atau isi manual bila tidak terbaca.'; }
    pdfApplyReady();
  }
  function pdfApplyReady(){
    var selected = Array.from(pe('values').querySelectorAll('select')).some(function(s){ return s.value.trim(); });
    pe('apply').disabled = pdf.busy || !selected || (pdf.category === 'identity' && ['owner','spouse','debtor'].indexOf(pe('role').value)<0);
  }
  pe('role').addEventListener('change', pdfApplyReady);
  pe('values').addEventListener('change', pdfApplyReady);
  pe('person').addEventListener('change', pdfValues);
  pe('apply').addEventListener('click', function(){
    pdfApplyReady(); if(pe('apply').disabled){ return; }
    var role = pe('role').value;
    if(pdf.category === 'identity' && ['owner','spouse','debtor'].indexOf(role)<0){ pdfStatus('Pilih tujuan identitas dahulu.'); return; }
    var changes = [], skipped = 0;
    pe('values').querySelectorAll('select').forEach(function(select){
      if(!select.value){ return; }
      var key = (pdf.category === 'identity' ? role + '_' : '') + select.dataset.key;
      var ctrl = document.getElementById('f_' + key);
      if(!ctrl || ctrl.disabled){ skipped++; return; }
      if(ctrl.value && ctrl.value !== select.value && !pe('overwrite').checked){ skipped++; return; }
      changes.push({ctrl:ctrl, key:key, value:select.value, pages:select.options[select.selectedIndex].dataset.pages});
    });
    if(changes.some(function(c){ return c.ctrl.value && c.ctrl.value !== c.value; }) &&
      !window.confirm('Timpa kolom terisi dengan nilai PDF terpilih?')){ return; }
    changes.forEach(function(c){
      c.ctrl.value = c.value; c.ctrl.dispatchEvent(new Event('input',{bubbles:true}));
      reviewState.ocrData[c.key] = {value:c.value}; reviewState.sources[c.key] = 'PDF hal. ' + c.pages;
    });
    var applied = changes.length + ' kolom diisi; ' + skipped + ' dilewati (terisi/nonaktif). Untuk debitor berbeda atau alamat pasangan, aktifkan kolom terkait di formulir terlebih dahulu.';
    pdfStatus(applied);
    pe('applied').textContent = applied + ' Hasil tetap tersedia: pilih rekaman/tujuan lain lalu isi lagi tanpa scan ulang.';
  });
  pe('clear').addEventListener('click', function(){
    if(pdf.busy){ return; } ++pdf.version; pdf.data = null; pdf.records = []; pdf.pages = []; pdf.errors = []; pdf.count = 0; pe('apply').disabled = true;
    pe('file').value = ''; pe('values').replaceChildren(); pe('person').replaceChildren();
    pe('applied').textContent = '';
    pe('results').hidden = true; pe('consent').checked = false; pdfReady(); pdfStatus('PDF dan hasil dibersihkan. Nilai yang sudah diterapkan tetap di formulir.');
  });
  fetch('/api/ocr/status').then(function(r){ return r.json(); }).then(function(j){
    pe('provider').textContent = 'Penyedia melalui router: ' + j.ai.base_url_host + ' · model ' + j.ai.model + '. Dukungan/akurasi gambar belum dijamin.';
  }).catch(function(){ pe('provider').textContent = 'Status penyedia belum tersedia; periksa konfigurasi AI.'; });
'''
