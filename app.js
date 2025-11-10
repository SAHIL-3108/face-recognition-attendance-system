// frontend/app.js (v2.2 - Fixed Late Detection)
document.addEventListener('DOMContentLoaded', () => {
  const registerBtn = document.getElementById('registerBtn');
  const settingsBtn = document.getElementById('settingsBtn');
  const modal = document.getElementById('registrationModal');
  const settingsModal = document.getElementById('settingsModal');
  const closeModal = document.getElementById('closeModal');
  const closeSettingsModal = document.getElementById('closeSettingsModal');
  const registrationForm = document.getElementById('registrationForm');
  const settingsForm = document.getElementById('settingsForm');
  const registerMessage = document.getElementById('registerMessage');
  const settingsMessage = document.getElementById('settingsMessage');
  const startBtn = document.getElementById('startRecognition');
  const startOverlayBtn = document.getElementById('startRecognitionOverlay');
  const attendanceList = document.getElementById('attendanceList');
  const attendanceFilter = document.getElementById('attendanceFilter');
  const totalEmployeesEl = document.getElementById('totalEmployees');
  const presentTodayEl = document.getElementById('presentToday');
  const lateTodayEl = document.getElementById('lateToday');
  const absentTodayEl = document.getElementById('absentToday');
  const exportBtn = document.getElementById('exportBtn');
  const attendanceChartCanvas = document.getElementById('attendanceChart');
  const currentLateTimeEl = document.getElementById('currentLateTime');

  let recognitionRunning = false;
  let chart = null;
  let currentLateTime = "09:00";

  async function fetchEmployeesAndAttendance() {
    const empRes = await fetch('/employees'); 
    const users = await empRes.json();
    const attRes = await fetch('/attendance'); 
    const attendance = await attRes.json();
    return { users, attendance };
  }

  async function loadLateTime() {
    try {
      const res = await fetch('/get_late_time');
      if (res.ok) {
        const data = await res.json();
        currentLateTime = `${data.hour.toString().padStart(2, '0')}:${data.minute.toString().padStart(2, '0')}`;
        currentLateTimeEl.textContent = currentLateTime;
        
        // Update settings form
        document.getElementById('lateTimeHour').value = data.hour;
        document.getElementById('lateTimeMinute').value = data.minute;
      }
    } catch (err) {
      console.error('Failed to load late time:', err);
    }
  }

  function formatTimestamp(ts) {
    if (!ts) return '';
    const d = new Date(ts);
    if (isNaN(d)) return ts;
    const now = new Date();
    const sameDay = d.toDateString() === now.toDateString();
    const time = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    return sameDay ? `Today, ${time}` : `${d.toLocaleDateString()} ${time}`;
  }

  async function loadAttendance() {
    try {
      const { users, attendance } = await fetchEmployeesAndAttendance();
      const attMap = {};
      attendance.forEach(a => attMap[a.name] = a);

      console.log('Attendance data:', attendance); // Debug log
      console.log('Users data:', users); // Debug log

      const filter = attendanceFilter.value || 'present';
      let toRender;
      
      if (filter === 'present') 
        toRender = users.filter(u => u.checked_in_today && (!attMap[u.name] || !attMap[u.name].is_late));
      else if (filter === 'late')
        toRender = users.filter(u => u.checked_in_today && attMap[u.name] && attMap[u.name].is_late);
      else if (filter === 'absent') 
        toRender = users.filter(u => !u.checked_in_today);
      else 
        toRender = users;

      toRender.sort((a,b) => {
        if (a.checked_in_today === b.checked_in_today) {
          // Sort by late status first, then name
          const aIsLate = attMap[a.name] && attMap[a.name].is_late;
          const bIsLate = attMap[b.name] && attMap[b.name].is_late;
          if (aIsLate !== bIsLate) return aIsLate ? -1 : 1;
          return a.name.localeCompare(b.name);
        }
        return a.checked_in_today ? -1 : 1;
      });

      attendanceList.innerHTML = '';
      toRender.forEach(u => {
        const att = attMap[u.name];
        const timeStr = att ? formatTimestamp(att.check_in) : (u.last_check_in ? formatTimestamp(u.last_check_in) : '');
        
        let statusClass, statusText;
        if (u.checked_in_today) {
          if (att && att.is_late) {
            statusClass = 'status-late';
            statusText = 'late';
          } else {
            statusClass = 'status-present';
            statusText = 'present';
          }
        } else {
          statusClass = 'status-absent';
          statusText = 'absent';
        }

        const item = document.createElement('div');
        item.className = 'attendance-item';
        item.innerHTML = `
          <div class="user-info">
            <div class="user-avatar">${(u.name || '').split(' ').map(x=>x[0]).slice(0,2).join('').toUpperCase()}</div>
            <div>
              <div class="user-name">${u.name}</div>
              <div class="time-stamp">${timeStr}</div>
            </div>
          </div>
          <div style="display:flex;gap:8px;align-items:center">
            <div class="status-badge ${statusClass}">${statusText}</div>
            <button class="btn-small rename-btn" data-id="${u.id}" data-name="${u.name}">Rename</button>
          </div>
        `;
        attendanceList.appendChild(item);
      });

      document.querySelectorAll('.rename-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
          const id = btn.dataset.id; const oldName = btn.dataset.name;
          const newName = prompt('Rename user', oldName);
          if (!newName || !newName.trim()) return;
          try {
            const r = await fetch('/rename_user', {
              method: 'POST', headers: {'Content-Type':'application/json'},
              body: JSON.stringify({id: Number(id), name: newName.trim()})
            });
            const j = await r.json();
            if (j.success) loadAttendance();
            else alert('Rename failed');
          } catch (err) { console.error(err); alert('Rename failed'); }
        });
      });

      // Calculate counts
      const presentCount = users.filter(u => u.checked_in_today && (!attMap[u.name] || !attMap[u.name].is_late)).length;
      const lateCount = users.filter(u => u.checked_in_today && attMap[u.name] && attMap[u.name].is_late).length;
      const absentCount = users.filter(u => !u.checked_in_today).length;

      console.log('Counts - Present:', presentCount, 'Late:', lateCount, 'Absent:', absentCount); // Debug log

      totalEmployeesEl.textContent = users.length;
      presentTodayEl.textContent = presentCount;
      lateTodayEl.textContent = lateCount;
      absentTodayEl.textContent = absentCount;
    } catch (err) {
      console.error('loadAttendance error', err);
    }
  }

  async function loadWeeklyChart() {
    try {
      const res = await fetch('/attendance_weekly');
      if (!res.ok) return;
      const js = await res.json();
      const labels = js.labels || []; const counts = js.counts || [];
      if (!chart) {
        chart = new Chart(attendanceChartCanvas.getContext('2d'), {
          type: 'bar',
          data: { labels, datasets: [{ label: 'Present', data: counts, backgroundColor: 'rgba(67,97,238,0.9)', borderRadius: 6 }] },
          options: { responsive: true, plugins:{legend:{display:false}}, scales:{y:{beginAtZero:true, ticks:{precision:0}}} }
        });
      } else {
        chart.data.labels = labels; chart.data.datasets[0].data = counts; chart.update();
      }
    } catch (err) { console.error('chart load error', err); }
  }

  async function toggleRecognition() {
    try {
      if (!recognitionRunning) {
        const r = await fetch('/start_recognition'); const j = await r.json();
        if (j.status) { recognitionRunning = true; startBtn.innerHTML = '<i class="fas fa-stop"></i> Stop Recognition'; startOverlayBtn.innerHTML = '<i class="fas fa-stop"></i> Stop Recognition'; }
      } else {
        const r = await fetch('/stop_recognition'); const j = await r.json();
        recognitionRunning = false; startBtn.innerHTML = '<i class="fas fa-camera"></i> Start Recognition'; startOverlayBtn.innerHTML = '<i class="fas fa-camera"></i> Start Recognition';
      }
    } catch (err) { console.error(err); alert('Recognition failed'); }
  }

  // Event Listeners
  startBtn.addEventListener('click', toggleRecognition);
  startOverlayBtn.addEventListener('click', toggleRecognition);
  registerBtn.addEventListener('click', () => modal.style.display = 'flex');
  settingsBtn.addEventListener('click', () => settingsModal.style.display = 'flex');
  closeModal.addEventListener('click', () => modal.style.display = 'none');
  closeSettingsModal.addEventListener('click', () => settingsModal.style.display = 'none');
  
  window.addEventListener('click', e => { 
    if (e.target === modal) modal.style.display = 'none';
    if (e.target === settingsModal) settingsModal.style.display = 'none';
  });

  registrationForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    registerMessage.textContent = 'Uploading...';
    const name = document.getElementById('employeeName').value.trim();
    const employee_id = document.getElementById('employeeId').value.trim();
    const file = document.getElementById('faceImage').files[0];
    if (!name || !employee_id || !file) { registerMessage.textContent = 'Please fill all fields.'; return; }
    const fd = new FormData(); fd.append('name', name); fd.append('employee_id', employee_id); fd.append('image', file);
    try {
      const res = await fetch('/register_face', { method: 'POST', body: fd });
      const j = await res.json();
      registerMessage.textContent = j.message || (j.success ? 'Registered' : 'Failed');
      if (j.success) { setTimeout(()=> { modal.style.display='none'; registrationForm.reset(); registerMessage.textContent=''; loadAttendance(); loadWeeklyChart(); }, 700); }
    } catch (err) { registerMessage.textContent = 'Upload failed'; console.error(err); }
  });

  settingsForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    settingsMessage.textContent = 'Saving...';
    
    const hour = parseInt(document.getElementById('lateTimeHour').value);
    const minute = parseInt(document.getElementById('lateTimeMinute').value);
    
    if (isNaN(hour) || isNaN(minute) || hour < 0 || hour > 23 || minute < 0 || minute > 59) {
      settingsMessage.textContent = 'Please enter valid time (hour: 0-23, minute: 0-59)';
      return;
    }
    
    try {
      const res = await fetch('/set_late_time', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ hour, minute })
      });
      
      const j = await res.json();
      if (j.success) {
        settingsMessage.textContent = j.message;
        currentLateTime = j.late_time;
        currentLateTimeEl.textContent = currentLateTime;
        setTimeout(() => {
          settingsModal.style.display = 'none';
          settingsMessage.textContent = '';
          loadAttendance(); // Reload to update late status
        }, 1000);
      } else {
        settingsMessage.textContent = j.message || 'Failed to save settings';
      }
    } catch (err) {
      settingsMessage.textContent = 'Save failed';
      console.error(err);
    }
  });

  attendanceFilter.addEventListener('change', loadAttendance);
  exportBtn.addEventListener('click', async () => {
    exportBtn.disabled = true; exportBtn.textContent = 'Preparing...';
    try {
      const resp = await fetch('/export_attendance?range=week');
      if (!resp.ok) throw new Error('Export failed');
      const blob = await resp.blob();
      const cd = resp.headers.get('Content-Disposition') || '';
      let filename = 'attendance_export';
      const m = /filename="?([^"]+)"?/.exec(cd);
      if (m) filename = m[1];
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a'); a.href = url; a.download = filename; document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
    } catch (err) { alert('Export failed'); console.error(err); }
    finally { exportBtn.disabled = false; exportBtn.textContent = 'Export'; }
  });

  // initial load and periodic refresh
  loadLateTime();
  loadAttendance(); 
  loadWeeklyChart();
  setInterval(loadAttendance, 20_000);
  setInterval(loadWeeklyChart, 30_000);
  setInterval(loadLateTime, 60_000); // Refresh late time every minute
});