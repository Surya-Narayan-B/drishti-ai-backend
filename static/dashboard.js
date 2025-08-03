document.addEventListener('DOMContentLoaded', () => {
    // --- Element References ---
    const startSessionBtn = document.getElementById('start-session-btn');
    const stopSessionBtn = document.getElementById('stop-session-btn');
    const viewReportBtn = document.getElementById('view-report-btn');
    const closeModalBtn = document.getElementById('close-modal-btn');
    const chatForm = document.getElementById('chat-form');
    const chatInput = document.getElementById('chat-input');
    const chatMessages = document.getElementById('chat-messages');
    const themeToggleBtn = document.getElementById('theme-toggle-btn');
    const mainHeaderTitle = document.querySelector('.header-content h1'); // For name display
    
    const idleView = document.getElementById('idle-view');
    const liveView = document.getElementById('live-view');
    const reportModal = document.getElementById('report-modal');
    const body = document.body;

    // --- Settings Modal Element References ---
    const settingsBtn = document.getElementById('settings-btn');
    const settingsModal = document.getElementById('settings-modal');
    const closeSettingsModalBtn = document.getElementById('close-settings-modal-btn');
    const saveSettingsBtn = document.getElementById('save-settings-btn');
    const tabLinks = document.querySelectorAll('.tab-link');
    const tabContents = document.querySelectorAll('.tab-content');
    const blinkRateGoal = document.getElementById('blink-rate-goal');
    const userNameInputSettings = document.getElementById('user-name-settings'); // Name input in settings
    
    const currentStreakEl = document.getElementById('current-streak');

    // --- Session Report Modal Element References ---
    const sessionReportModal = document.getElementById('session-report-modal');
    const closeSessionReportBtn = document.getElementById('close-session-report-btn');
    const sessionReportLoader = document.getElementById('session-report-loader');
    const sessionReportContent = document.getElementById('session-report-content');
    const reportActiveTime = document.getElementById('report-active-time');
    const reportGoalAchievement = document.getElementById('report-goal-achievement');
    const reportPerformance = document.getElementById('report-performance');

    // --- Calibration Modal Element References ---
    const calibrationModal = document.getElementById('calibration-modal');
    const startCalibrationBtn = document.getElementById('start-calibration-btn');
    const recalibrateBtn = document.getElementById('recalibrate-btn');
    const calibrationStatus = document.getElementById('calibration-status');
    const userNameInputCalibration = document.getElementById('user-name-calibration'); // Name input in calibration

    // --- State Management ---
    let isSessionActive = false;
    let fetchDataInterval = null;

    // --- Chart Instances ---
    let liveBlinkChart, fatigueHotspotsChart, activityClockChart, weeklyReportChart;

    // --- DARK MODE THEME LOGIC ---
    const applyTheme = (theme) => {
        if (theme === 'dark') {
            body.classList.add('dark-mode');
            themeToggleBtn.textContent = '☀️';
        } else {
            body.classList.remove('dark-mode');
            themeToggleBtn.textContent = '🌗';
        }
    };

    const initializeTheme = () => {
        const savedTheme = localStorage.getItem('theme');
        if (savedTheme) {
            applyTheme(savedTheme);
        } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            applyTheme('dark');
        } else {
            applyTheme('light');
        }
    };

    const toggleTheme = () => {
        const isDarkMode = body.classList.toggle('dark-mode');
        const newTheme = isDarkMode ? 'dark' : 'light';
        applyTheme(newTheme);
        localStorage.setItem('theme', newTheme);
    };

    // --- SETTINGS MODAL LOGIC ---
    function openSettingsModal() {
        settingsModal.classList.remove('hidden');
        loadSettings();
    }

    function closeSettingsModal() {
        settingsModal.classList.add('hidden');
    }

    function handleTabClick(event) {
        const clickedTab = event.target.closest('.tab-link');
        if (!clickedTab) return;

        tabLinks.forEach(link => link.classList.remove('active'));
        tabContents.forEach(content => content.style.display = 'none');

        clickedTab.classList.add('active');
        const tabId = clickedTab.dataset.tab;
        document.getElementById(tabId).style.display = 'block';
    }
    
    // --- CALIBRATION MODAL LOGIC ---
    async function openCalibrationModal() {
    try {
        // Fetch the latest settings from the server
        const response = await fetch('/api/get_settings');
        const settings = await response.json();
        
        // Pre-fill the name if it exists
        if (settings.user_name && settings.user_name !== 'User') {
            userNameInputCalibration.value = settings.user_name;
        }
    } catch (error) {
        console.error("Failed to pre-load user name for calibration:", error);
    }

    calibrationStatus.textContent = 'Ready when you are.';
    startCalibrationBtn.disabled = false;
    calibrationModal.classList.remove('hidden');
}
    async function handleStartCalibration() {
        // Validate and get user name
        const userName = userNameInputCalibration.value.trim();
        if (!userName) {
            calibrationStatus.textContent = 'Please enter your name to begin.';
            return;
        }

        calibrationStatus.textContent = 'Calibrating... Please follow instructions on the camera window.';
        startCalibrationBtn.disabled = true;
        try {
        const response = await fetch('/api/start_calibration', { 
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_name: userName })
        });
        
        const result = await response.json();

        if (result.status === 'complete') {
            calibrationStatus.textContent = 'Calibration Complete! Reloading...';
            // Reload the page after a short delay
            setTimeout(() => {
                window.location.reload();
            }, 1500);
        } else {
            throw new Error(result.message || 'Calibration failed on the server.');
        }

    } catch (error) {
        console.error("Calibration error:", error);
        calibrationStatus.textContent = `Error: ${error.message}. Please try again.`;
        startCalibrationBtn.disabled = false;
    }
    }

    // --- UI Update Functions ---
    function updateUIForSessionState() {
        if (isSessionActive) {
            idleView.classList.add('hidden');
            liveView.classList.remove('hidden');
            fetchDataInterval = setInterval(fetchLiveData, 3000);
            fetchLiveData();
        } else {
            liveView.classList.add('hidden');
            idleView.classList.remove('hidden');
            if (fetchDataInterval) {
                clearInterval(fetchDataInterval);
            }
            fetchSummaryData();
        }
    }

    // --- API Communication & Data Handling ---
    async function loadSettings() {
        try {
            const response = await fetch('/api/get_settings');
            const settings = await response.json();
            
            // Handle user name display
            if (settings.user_name && settings.user_name !== 'User') {
                mainHeaderTitle.textContent = `${settings.user_name}'s Wellness Dashboard`;
                userNameInputSettings.value = settings.user_name;
            } else {
                mainHeaderTitle.textContent = 'Your Wellness Dashboard';
                userNameInputSettings.value = '';
            }
            
            document.getElementById('goal-blink-rate').value = settings.goal_blink_rate || '';
            document.getElementById('goal-breaks').value = settings.goal_breaks || '';
            document.getElementById('enable-weekly-goals').checked = settings.enable_weekly_goals;
            document.getElementById('enable-daily-streak').checked = settings.enable_daily_streak;
            document.getElementById('master-notifications').checked = settings.master_notifications;
            document.getElementById('notify-blink').checked = settings.notify_blink;
            document.getElementById('notify-break').checked = settings.notify_break;
            document.getElementById('notify-frequency').value = settings.notify_frequency;
            document.getElementById('active-start-time').value = settings.active_start_time;
            document.getElementById('active-end-time').value = settings.active_end_time;

            if (settings.goal_blink_rate) {
                blinkRateGoal.textContent = `Goal: ${settings.goal_blink_rate} BPM`;
            } else {
                blinkRateGoal.textContent = '';
            }
        } catch (error) {
            console.error("Failed to load settings:", error);
        }
    }

    async function saveSettings() {
        const settingsData = {
            userName: userNameInputSettings.value.trim(), // Include user name
            goalBlinkRate: document.getElementById('goal-blink-rate').value,
            goalBreaks: document.getElementById('goal-breaks').value,
            enableWeeklyGoals: document.getElementById('enable-weekly-goals').checked,
            enableDailyStreak: document.getElementById('enable-daily-streak').checked,
            masterNotifications: document.getElementById('master-notifications').checked,
            notifyBlink: document.getElementById('notify-blink').checked,
            notifyBreak: document.getElementById('notify-break').checked,
            notifyFrequency: document.getElementById('notify-frequency').value,
            activeStartTime: document.getElementById('active-start-time').value,
            activeEndTime: document.getElementById('active-end-time').value,
        };

        try {
            const response = await fetch('/api/save_settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(settingsData)
            });
            if (!response.ok) throw new Error('Failed to save settings');
            
            // Update header with new name
            if (settingsData.userName) {
                mainHeaderTitle.textContent = `${settingsData.userName}'s Wellness Dashboard`;
            } else {
                mainHeaderTitle.textContent = 'Your Wellness Dashboard';
            }

            if (settingsData.goalBlinkRate) {
                blinkRateGoal.textContent = `Goal: ${settingsData.goalBlinkRate} BPM`;
            } else {
                blinkRateGoal.textContent = '';
            }
            fetchSummaryData(); 
            closeSettingsModal();
        } catch(error) {
            console.error("Failed to save settings:", error);
        }
    }
    
    async function startMonitoringSession() {
        try {
            await fetch('/api/start_monitoring', { method: 'POST' });
            isSessionActive = true;
            updateUIForSessionState();
        } catch (error) {
            console.error('Failed to start monitoring session:', error);
        }
    }

    async function stopMonitoringSession() {
        try {
            sessionReportModal.classList.remove('hidden');
            sessionReportLoader.classList.remove('hidden');
            sessionReportContent.classList.add('hidden');

            const stopResponse = await fetch('/api/stop_monitoring', { method: 'POST' });
            const stopData = await stopResponse.json();
            const sessionId = stopData.session_id;

            isSessionActive = false;
            updateUIForSessionState();

            if (sessionId) {
                const reportResponse = await fetch(`/api/session_report/${sessionId}`);
                const reportData = await reportResponse.json();
                populateReportModal(reportData);
            } else {
                sessionReportContent.innerHTML = '<p>Could not retrieve session report.</p>';
                sessionReportLoader.classList.add('hidden');
                sessionReportContent.classList.remove('hidden');
            }
        } catch (error) {
            console.error('Failed to stop monitoring session or fetch report:', error);
            sessionReportContent.innerHTML = `<p>An error occurred: ${error.message}</p>`;
            sessionReportLoader.classList.add('hidden');
            sessionReportContent.classList.remove('hidden');
        }
    }

    function populateReportModal(data) {
        if (data.error) {
            reportActiveTime.textContent = data.error;
            reportGoalAchievement.innerHTML = '';
            reportPerformance.innerHTML = '';
        } else {
            reportActiveTime.textContent = data.active_time_str;

            let goalHtml = '';
            if (data.goal_achievement.blink_rate) {
                const goal = data.goal_achievement.blink_rate;
                const icon = goal.status === 'good' ? '✅' : '⚠️';
                goalHtml += `<div class="report-item"><span class="report-item-icon ${goal.status}">${icon}</span><div class="report-item-details"><span class="report-item-label">Blink Rate Goal</span><p class="report-item-value">${goal.text}</p></div></div>`;
            }
            reportGoalAchievement.innerHTML = goalHtml || '<p>No goals were set for this session.</p>';

            let perfHtml = '';
            const perfMetrics = [
                { key: 'blink_rate', name: 'Blink Rate' },
                { key: 'fatigue_events', name: 'Fatigue Events' },
                { key: 'stares', name: 'Stare Alerts' },
            ];
            perfMetrics.forEach(metric => {
                const perf = data.performance[metric.key];
                if (perf) {
                    perfHtml += `<div class="report-item"><div class="report-item-details"><span class="report-item-label">${metric.name}</span><p class="report-item-value">This Session: <strong>${perf.session}</strong> | Historical Avg: <strong>${perf.historical}</strong></p>${perf.insight ? `<p class="report-item-insight status-${perf.status}">${perf.insight}</p>` : ''}</div></div>`;
                }
            });
            reportPerformance.innerHTML = perfHtml;
        }

        sessionReportLoader.classList.add('hidden');
        sessionReportContent.classList.remove('hidden');
    }

    async function fetchLiveData() {
        try {
            const response = await fetch('/api/stats');
            const data = await response.json();
             console.log(data);
            document.getElementById('total-blinks').textContent = data.blinks;
            // document.getElementById('total-yawns').textContent = data.yawns;
            if (document.getElementById('fatigue-score-value')) {
             document.getElementById('fatigue-score-value').textContent = data.fatigue_score;
            }
            const hours = Math.floor(data.active_time / 3600);
            const minutes = Math.floor((data.active_time % 3600) / 60);
            document.getElementById('active-time').textContent = `${hours}h ${minutes}m`;
            updateLiveChart(data.bpm);
        } catch (error) {
            console.error('Failed to fetch live data:', error);
            isSessionActive = false;
            updateUIForSessionState();
        }
    }

    async function fetchSummaryData() {
        try {
            const response = await fetch('/api/summary_stats');
            const data = await response.json();
            document.getElementById('health-score').textContent = `${data.health_score} / 100`;
            document.getElementById('avg-blink-rate').textContent = `${data.avg_blink_rate} BPM`;
            if (data.current_streak !== undefined) {
                currentStreakEl.innerHTML = `🔥 ${data.current_streak} Day${data.current_streak === 1 ? '' : 's'}`;
            }
            updateFatigueHotspotsChart(data.fatigue_hotspots);
            updateActivityClockChart(data.activity_clock);
        } catch (error) {
            console.error('Failed to fetch summary data:', error);
        }
    }

    async function fetchWeeklyReport() {
        try {
            const response = await fetch('/api/weekly_report');
            const data = await response.json();
            updateWeeklyReportChart(data);
        } catch (error) {
            console.error('Failed to fetch weekly report:', error);
        }
    }

    // --- Chart Initialization and Updates ---
    function initializeCharts() {
        const softBlue = '#7DD3FC';
        const softOrange = '#FDBA74';
        const softIndigo = '#818CF8';
        const activityPalette = ['#818CF8', '#A5B4FC', '#7DD3FC', '#FDBA74', '#FDE047', '#C4B5FD'];
        const liveCtx = document.getElementById('liveBlinkChart').getContext('2d');
        liveBlinkChart = new Chart(liveCtx, { type: 'line', data: { labels: [], datasets: [{ label: 'Blinks Per Minute', data: [], borderColor: softIndigo, tension: 0.4, fill: true, backgroundColor: 'rgba(129, 140, 248, 0.1)' }] }, options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true } } } });
        const fatigueCtx = document.getElementById('fatigueHotspotsChart').getContext('2d');
        fatigueHotspotsChart = new Chart(fatigueCtx, { type: 'bar', data: { labels: [], datasets: [{ label: 'Fatigue Events', data: [], backgroundColor: softOrange }] }, options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true } } } });
        const activityCtx = document.getElementById('activityClockChart').getContext('2d');
        activityClockChart = new Chart(activityCtx, { type: 'polarArea', data: { labels: [], datasets: [{ label: 'Screen Time Activity', data: [], backgroundColor: activityPalette }] }, options: { responsive: true, maintainAspectRatio: false } });
        const weeklyCtx = document.getElementById('weeklyReportChart').getContext('2d');
        weeklyReportChart = new Chart(weeklyCtx, { type: 'bar', data: { labels: [], datasets: [{ label: 'Screen Time (Hours)', data: [], backgroundColor: softBlue }] }, options: { responsive: true, maintainAspectRatio: true, scales: { y: { beginAtZero: true } } } });
    }

    function updateLiveChart(bpm) {
        const now = new Date();
        const timeLabel = `${now.getHours()}:${now.getMinutes()}:${now.getSeconds()}`;
        liveBlinkChart.data.labels.push(timeLabel);
        liveBlinkChart.data.datasets[0].data.push(bpm);
        if (liveBlinkChart.data.labels.length > 20) {
            liveBlinkChart.data.labels.shift();
            liveBlinkChart.data.datasets[0].data.shift();
        }
        liveBlinkChart.update();
    }

    function updateFatigueHotspotsChart(hotspotsData) {
        const labels = Object.keys(hotspotsData).map(hour => `${hour}:00`);
        const data = Object.values(hotspotsData);
        fatigueHotspotsChart.data.labels = labels;
        fatigueHotspotsChart.data.datasets[0].data = data;
        fatigueHotspotsChart.update();
    }

    function updateActivityClockChart(activityData) {
        const labels = Object.keys(activityData).map(hour => `${hour}:00`);
        const data = Object.values(activityData);
        activityClockChart.data.labels = labels;
        activityClockChart.data.datasets[0].data = data;
        activityClockChart.update();
    }
    
    function updateWeeklyReportChart(reportData) {
        weeklyReportChart.data.labels = reportData.labels;
        weeklyReportChart.data.datasets[0].data = reportData.data;
        weeklyReportChart.update();
    }

    // --- Chatbot Functions ---
    function addMessageToChat(message, sender) {
        const messageElement = document.createElement('div');
        messageElement.classList.add('message', `${sender}-message`);
        const p = document.createElement('p');
        p.textContent = message;
        messageElement.appendChild(p);
        chatMessages.appendChild(messageElement);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    async function handleChatSubmit(event) {
        event.preventDefault();
        const userMessage = chatInput.value.trim();
        if (!userMessage) return;
        addMessageToChat(userMessage, 'user');
        chatInput.value = '';
        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: userMessage }),
            });
            if (!response.ok) throw new Error('Network response was not ok');
            const data = await response.json();
            addMessageToChat(data.reply, 'bot');
        } catch (error) {
            console.error('Failed to get chat reply:', error);
            addMessageToChat("Sorry, I couldn't connect. Please try again.", 'bot');
        }
    }

    // --- Event Listeners ---
    startSessionBtn.addEventListener('click', startMonitoringSession);
    stopSessionBtn.addEventListener('click', stopMonitoringSession);
    viewReportBtn.addEventListener('click', () => {
        fetchWeeklyReport();
        reportModal.classList.remove('hidden');
    });
    closeModalBtn.addEventListener('click', () => {
        reportModal.classList.add('hidden');
    });
    reportModal.addEventListener('click', (event) => {
        if (event.target === reportModal) {
            reportModal.classList.add('hidden');
        }
    });
    chatForm.addEventListener('submit', handleChatSubmit);
    themeToggleBtn.addEventListener('click', toggleTheme);

    // Settings Listeners
    settingsBtn.addEventListener('click', openSettingsModal);
    closeSettingsModalBtn.addEventListener('click', closeSettingsModal);
    settingsModal.addEventListener('click', (event) => {
        if (event.target === settingsModal) {
            closeSettingsModal();
        }
    });
    tabLinks.forEach(link => {
        link.addEventListener('click', handleTabClick);
    });
    saveSettingsBtn.addEventListener('click', saveSettings);

    // Session Report Listeners
    closeSessionReportBtn.addEventListener('click', () => {
        sessionReportModal.classList.add('hidden');
    });
    sessionReportModal.addEventListener('click', (event) => {
        if (event.target === sessionReportModal) {
            sessionReportModal.classList.add('hidden');
        }
    });

    // Calibration Listeners
    startCalibrationBtn.addEventListener('click', handleStartCalibration);
    recalibrateBtn.addEventListener('click', () => {
        closeSettingsModal();
        openCalibrationModal();
    });

    // --- Initial Setup ---
    async function initializeApp() {
        try {
            const response = await fetch('/api/check_calibration');
            const data = await response.json();

            if (data.is_calibrated) {
                initializeTheme();
                initializeCharts();
                updateUIForSessionState();
                loadSettings(); // This will now also load and display the user's name
            } else {
                openCalibrationModal();
            }
        } catch (error) {
            console.error("Could not check calibration status:", error);
            calibrationStatus.textContent = "Could not connect to the server. Please ensure the backend is running and refresh the page.";
            openCalibrationModal();
        }
    }

    initializeApp();
});
