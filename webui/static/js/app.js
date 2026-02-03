// API基础URL
const API_BASE = '/api';

// 移除美化提示系统，使用原始浏览器弹窗

// 获取用户ID
function getUserId() {
    return localStorage.getItem('hanime_user_id') || '';
}

// 标记是否已经在处理401错误，防止重复重定向
let isHandling401 = false;

// 普通的fetch（使用 Session cookie 认证，不需要手动添加认证头）
async function authenticatedFetch(url, options = {}) {
    // 不需要手动添加认证头，Session cookie 会自动发送
    // options.headers = {
    //     ...options.headers,
    //     'X-API-Key': apiKey
    // };

    try {
        const response = await fetch(url, options);

        // 处理401未授权错误
        if (response.status === 401) {
            // 如果已经在处理401，直接抛出错误，不重复处理
            if (isHandling401) {
                console.warn('已经在处理401错误，跳过:', url);
                throw new Error('未授权，请重新登录');
            }

            isHandling401 = true;

            console.error('认证失败，清除登录状态:', url);

            // 清除登录状态
            localStorage.removeItem('hanime_user_id');
            localStorage.removeItem('hanime_username');
            localStorage.removeItem('hanime_logged_in');

            // 只在当前页面是主页时才重定向，避免无限循环
            if (window.location.pathname !== '/login.html' && !window.location.pathname.endsWith('.html')) {
                window.location.href = '/login.html';
            }

            setTimeout(() => {
                isHandling401 = false;
            }, 2000);

            throw new Error('未授权，请重新登录');
        }

        return response;
    } catch (error) {
        // 如果是已经抛出的401错误，直接抛出
        if (error.message === '未授权，请重新登录') {
            throw error;
        }
        console.error('请求失败:', url, error);
        throw error;
    }
}

// 当前活动标签页
let currentTab = 'tasks';

// 定时器引用
let refreshInterval = null;

// 清理过期图片缓存
function cleanupImageCache() {
    const now = Date.now();
    for (const [url, cacheEntry] of imageCache.entries()) {
        if (now - cacheEntry.timestamp >= IMAGE_CACHE_DURATION) {
            imageCache.delete(url);
        }
    }
}

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    // 首先检查登录状态
    const userId = getUserId();
    const isLoggedIn = localStorage.getItem('hanime_logged_in') === 'true';

    if (!userId || !isLoggedIn) {
        console.warn('未登录，跳转到登录页');
        window.location.href = '/login.html';
        return;
    }

    initTabs();
    initServerControl();
    initTasksTab();
    initVideosTab();
    initLogsTab();
    initSettingsTab();
    initUserInfo();

    // 延迟加载配置和检查服务器状态，确保其他初始化完成
    setTimeout(() => {
        loadConfig();
        checkServerStatus();
    }, 500);

    // 定时刷新（只在 Session 有效时才刷新）
    refreshInterval = setInterval(() => {
        // 检查是否仍然有有效的登录状态
        const currentUserId = getUserId();
        const currentIsLoggedIn = localStorage.getItem('hanime_logged_in') === 'true';

        if (!currentUserId || !currentIsLoggedIn) {
            console.warn('登录状态已失效，停止刷新');
            clearInterval(refreshInterval);  // 停止定时器
            return;
        }

        // 检查页面是否可见，如果不可见则不刷新
        if (document.hidden) {
            return;
        }

        // 刷新任务（视频总览不自动刷新）
        if (currentTab === 'tasks') {
            loadTasks();
        }

        // 定期清理过期图片缓存
        cleanupImageCache();

        // 刷新服务器状态（已经在 loadTasks 等函数中检查了防重复状态）
        checkServerStatus();
    }, 3000);

    // 监听页面可见性变化
    document.addEventListener('visibilitychange', () => {
        // 页面隐藏或显示时不再自动刷新任何内容
        // 保留空实现，便于后续扩展
        // console.log('页面可见性变化');
    });

    // 页面卸载时清除定时器
    window.addEventListener('beforeunload', () => {
        if (refreshInterval) {
            clearInterval(refreshInterval);
            refreshInterval = null;
        }
    });
});

// 初始化用户信息显示
function initUserInfo() {
    const userId = getUserId();
    const username = localStorage.getItem('hanime_username') || '未知用户';
    const apiKey = localStorage.getItem('hanime_api_key') || '';  // API key 用于显示和复制

    console.log('initUserInfo - userId:', userId, 'username:', username, 'apiKey exists:', !!apiKey);

    // 显示用户名
    const usernameDisplay = document.getElementById('username-display');
    if (usernameDisplay) {
        usernameDisplay.textContent = `用户: ${username}`;
    }

    if (userId) {
        console.log('已登录用户:', username, 'ID:', userId);
        if (apiKey) {
            console.log('API密钥:', apiKey.substring(0, 8) + '...');
        }
    }

    // API密钥按钮事件（弹窗）
    const apiKeyBtn = document.getElementById('api-key-btn');
    if (apiKeyBtn) {
        apiKeyBtn.addEventListener('click', showApiKeyModal);
    }

    // 退出登录按钮事件
    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', logout);
    }

    // 关闭API密钥弹窗
    const closeApiKeyModal = document.getElementById('close-api-key-modal');
    if (closeApiKeyModal) {
        closeApiKeyModal.addEventListener('click', hideApiKeyModal);
    }

    // 复制API密钥（弹窗）
    const copyApiKeyBtn = document.getElementById('copy-api-key-btn');
    if (copyApiKeyBtn) {
        copyApiKeyBtn.addEventListener('click', copyApiKey);
    }

    // 复制API密钥（设置页面）
    const copyApiKeyBtnInline = document.getElementById('copy-api-key-btn-inline');
    if (copyApiKeyBtnInline) {
        copyApiKeyBtnInline.addEventListener('click', copyApiKeyInline);
    }

    // 检查是否为 admin 用户，控制监控按钮显示
    const serverStatusDiv = document.querySelector('.server-status');
    if (serverStatusDiv && username !== 'admin') {
        serverStatusDiv.style.display = 'none';
    }

    // 重新生成API密钥
    const regenerateApiKeyBtn = document.getElementById('regenerate-api-key-btn');
    if (regenerateApiKeyBtn) {
        regenerateApiKeyBtn.addEventListener('click', regenerateApiKey);
    }

    // 点击弹窗外部关闭
    const apiKeyModal = document.getElementById('api-key-modal');
    if (apiKeyModal) {
        apiKeyModal.addEventListener('click', (e) => {
            if (e.target === apiKeyModal) {
                hideApiKeyModal();
            }
        });
    }

    // 更新设置页面的API key显示
    updateSettingsApiKeyDisplay();
}

// 更新设置页面的API key显示
function updateSettingsApiKeyDisplay() {
    const apiKey = localStorage.getItem('hanime_api_key') || '';
    const settingsApiKeyInput = document.getElementById('settings-api-key');
    if (settingsApiKeyInput) {
        settingsApiKeyInput.value = apiKey;
    }
}

// 显示API密钥弹窗
function showApiKeyModal() {
    const modal = document.getElementById('api-key-modal');
    const apiKeyInput = document.getElementById('modal-api-key');
    if (modal && apiKeyInput) {
        const apiKey = localStorage.getItem('hanime_api_key') || '';
        apiKeyInput.value = apiKey;
        modal.classList.add('show');
    }
}

// 隐藏API密钥弹窗
function hideApiKeyModal() {
    const modal = document.getElementById('api-key-modal');
    if (modal) {
        modal.classList.remove('show');
    }
}

// 复制API密钥
async function copyApiKey() {
    const apiKeyInput = document.getElementById('modal-api-key');
    const apiKey = apiKeyInput.value;

    // 优先使用 navigator.clipboard
    if (navigator.clipboard && navigator.clipboard.writeText) {
        try {
            await navigator.clipboard.writeText(apiKey);
            const btn = document.getElementById('copy-api-key-btn');
            btn.textContent = '已复制!';
            setTimeout(() => {
                btn.textContent = '复制';
            }, 2000);
            return;
        } catch (err) {
            console.error('navigator.clipboard 复制失败，尝试降级方案:', err);
        }
    }

    // 降级方案：使用 document.execCommand
    try {
        apiKeyInput.select();
        apiKeyInput.setSelectionRange(0, 99999); // 兼容移动端
        const successful = document.execCommand('copy');
        if (successful) {
            const btn = document.getElementById('copy-api-key-btn');
            btn.textContent = '已复制!';
            setTimeout(() => {
                btn.textContent = '复制';
            }, 2000);
        } else {
            throw new Error('execCommand copy failed');
        }
    } catch (err) {
        console.error('复制失败:', err);
        alert('复制失败，请手动复制');
    }
}

// 登出
function logout() {
    if (confirm('确定要退出登录吗？')) {
        // 先调用后端登出 API 清除 Session（不使用 authenticatedFetch，避免401触发重定向）
        fetch('/api/auth/logout', { method: 'POST' })
            .then(() => {
                // 清除本地存储
                localStorage.removeItem('hanime_user_id');
                localStorage.removeItem('hanime_username');
                localStorage.removeItem('hanime_logged_in');
                // 保留 API key，因为它用于脚本调用
                // 跳转到登录页
                window.location.href = '/login.html';
            })
            .catch(err => {
                console.error('登出失败:', err);
                // 即使后端调用失败，也清除本地存储并跳转到登录页
                localStorage.removeItem('hanime_user_id');
                localStorage.removeItem('hanime_username');
                localStorage.removeItem('hanime_logged_in');
                window.location.href = '/login.html';
            });
    }
}

// 复制API密钥（设置页面）
function copyApiKeyInline() {
    const apiKeyInput = document.getElementById('settings-api-key');
    const apiKey = apiKeyInput.value;

    if (!apiKey) {
        alert('没有API密钥，请先登录');
        return;
    }

    // 优先使用 navigator.clipboard
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(apiKey).then(() => {
            const btn = document.getElementById('copy-api-key-btn-inline');
            const originalText = btn.textContent;
            btn.textContent = '已复制!';
            setTimeout(() => {
                btn.textContent = originalText;
            }, 2000);
        }).catch(err => {
            console.error('navigator.clipboard 复制失败，尝试降级方案:', err);
            fallbackCopy(apiKeyInput, apiKey);
        });
    } else {
        fallbackCopy(apiKeyInput, apiKey);
    }
}

// 降级复制方案
function fallbackCopy(inputElement, text) {
    try {
        inputElement.select();
        inputElement.setSelectionRange(0, 99999); // 兼容移动端
        const successful = document.execCommand('copy');

        // 取消选中文本
        inputElement.setSelectionRange(0, 0);
        inputElement.blur();

        if (successful) {
            const btn = document.getElementById('copy-api-key-btn-inline');
            const originalText = btn.textContent;
            btn.textContent = '已复制!';
            setTimeout(() => {
                btn.textContent = originalText;
            }, 2000);
        } else {
            throw new Error('execCommand copy failed');
        }
    } catch (err) {
        console.error('复制失败:', err);
        alert('复制失败，请手动复制');
    }
}

// 重新生成API密钥
function regenerateApiKey() {
    const passwordInput = document.getElementById('regenerate-password');
    const password = passwordInput.value.trim();

    if (!password) {
        alert('请输入密码验证');
        return;
    }

    const userId = getUserId();
    if (!userId) {
        alert('未登录');
        return;
    }

    if (!confirm('确定要重新生成API密钥吗？旧的API密钥将失效！')) {
        return;
    }

    const btn = document.getElementById('regenerate-api-key-btn');
    btn.disabled = true;
    btn.textContent = '处理中...';

    authenticatedFetch('/api/auth/regenerate-api-key', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, password: password })
    })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // 更新本地存储
                localStorage.setItem('hanime_api_key', data.api_key);
                updateSettingsApiKeyDisplay();

                alert('API密钥已重新生成，请更新油猴脚本中的配置');
                passwordInput.value = '';
            } else {
                alert(data.detail || '操作失败');
            }
        })
        .catch(err => {
            console.error('重新生成API密钥失败:', err);
            alert('操作失败: ' + err.message);
        })
        .finally(() => {
            btn.disabled = false;
            btn.textContent = '重新生成';
        });
}

// 标签页切换
function initTabs() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tab = btn.dataset.tab;
            switchTab(tab);
        });
    });
    // 移除了动态添加登出按钮的代码，因为HTML中已经有退出按钮
}

function switchTab(tab) {
    currentTab = tab;
    
    // 更新按钮状态
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tab);
    });
    
    // 更新内容显示
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.toggle('active', content.id === `tab-${tab}`);
    });

    // 加载对应数据
    if (tab === 'tasks') {
        loadTasks();
    } else if (tab === 'videos') {
        // 切换到视频标签页时总是重新加载数据，确保显示最新内容
        loadVideos();
        // 切换到视频标签页时立即检查更新
        setTimeout(() => checkVideoUpdates(), 500);
    } else if (tab === 'logs') {
        loadLogs();
    }
}

// 服务器控制
function initServerControl() {
    const toggleBtn = document.getElementById('server-toggle-btn');
    toggleBtn.addEventListener('click', toggleServer);
}

// 服务器状态检查状态，防止重复检查
let isCheckingServerStatus = false;
let serverStatusCheckPromise = null;

async function checkServerStatus() {
    // 如果正在检查，返回已有的 Promise
    if (isCheckingServerStatus && serverStatusCheckPromise) {
        return serverStatusCheckPromise;
    }

    isCheckingServerStatus = true;

    serverStatusCheckPromise = (async () => {
        try {
            const response = await authenticatedFetch(`${API_BASE}/server/status`);

            if (!response.ok) {
                updateServerStatus(false, false);
                return;
            }

            const data = await response.json();
            updateServerStatus(data.server_running, data.monitor_running);
        } catch (error) {
            updateServerStatus(false, false);
            console.error('检查服务器状态失败:', error);
        } finally {
            isCheckingServerStatus = false;
            serverStatusCheckPromise = null;
        }
    })();

    return serverStatusCheckPromise;
}

// 保存上一次的服务器状态，避免不必要的 DOM 更新
let lastServerStatus = { serverRunning: null, monitorRunning: null };

function updateServerStatus(serverRunning, monitorRunning) {
    const indicator = document.getElementById('server-status-indicator');
    const text = document.getElementById('server-status-text');
    const btn = document.getElementById('server-toggle-btn');

    // 如果状态没有变化，不更新 DOM
    if (lastServerStatus.serverRunning === serverRunning && lastServerStatus.monitorRunning === monitorRunning) {
        return;
    }

    // 更新状态
    lastServerStatus = { serverRunning, monitorRunning };

    if (serverRunning && monitorRunning) {
        indicator.className = 'status-indicator status-online';
        text.textContent = '监控服务: 运行中';
        btn.textContent = '停止监控';
        btn.disabled = false;
    } else if (serverRunning) {
        indicator.className = 'status-indicator status-offline';
        text.textContent = '监控服务: 已停止';
        btn.textContent = '启动监控';
        btn.disabled = false;
    } else {
        indicator.className = 'status-indicator status-offline';
        text.textContent = '服务器: 未启动';
        btn.textContent = '启动监控';
        btn.disabled = true;
    }
}

async function toggleServer() {
    const btn = document.getElementById('server-toggle-btn');
    btn.disabled = true;

    try {
        // 获取当前状态
        await checkServerStatus();
        const isRunning = document.getElementById('server-status-text').textContent.includes('运行中');

        const endpoint = isRunning ? '/server/stop' : '/server/start';
        const response = await authenticatedFetch(`${API_BASE}${endpoint}`, {
            method: 'POST'
        });

        if (response.ok) {
            const data = await response.json();
            if (data.success) {
                // 等待一下再检查状态（只调用一次）
                setTimeout(() => checkServerStatus(), 500);
            } else {
                // 失败时也需要检查状态
                checkServerStatus();
            }
        } else {
            // 请求失败时检查状态
            checkServerStatus();
        }
    } catch (error) {
        alert('操作失败: ' + error.message);
        // 错误时检查状态
        checkServerStatus();
    } finally {
        btn.disabled = false;
    }
}

// ========== 任务列表 ==========

function initTasksTab() {
    document.getElementById('refresh-tasks-btn').addEventListener('click', loadTasks);
    document.getElementById('delete-completed-tasks-btn').addEventListener('click', deleteCompletedTasks);
    document.getElementById('delete-all-tasks-btn').addEventListener('click', deleteAllTasks);
    document.getElementById('task-filter').addEventListener('change', loadTasks);
}

// 任务加载状态，防止重复加载
let isLoadingTasks = false;

// 保存上次加载的任务数据，用于对比
let lastTasksData = null;

async function loadTasks() {
    // 如果正在加载，直接返回
    if (isLoadingTasks) {
        return;
    }

    isLoadingTasks = true;

    const filter = document.getElementById('task-filter').value;
    const tbody = document.getElementById('tasks-tbody');

    // 只在第一次加载时显示"加载中..."
    if (!lastTasksData) {
        tbody.innerHTML = '<tr><td colspan="7" class="empty-message">加载中...</td></tr>';
    }

    try {
        const url = filter === 'all'
            ? `${API_BASE}/tasks`
            : `${API_BASE}/tasks?status=${filter}`;

        const response = await authenticatedFetch(url);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();

        if (data.tasks && data.tasks.length > 0) {
            // 检查任务是否真的变化了
            const tasksString = JSON.stringify(data.tasks);
            if (lastTasksData !== tasksString) {
                renderTasks(data.tasks);
                lastTasksData = tasksString;
            }
        } else {
            tbody.innerHTML = '<tr><td colspan="7" class="empty-message">暂无任务</td></tr>';
            lastTasksData = null;
        }
    } catch (error) {
        tbody.innerHTML = '<tr><td colspan="7" class="empty-message">加载失败</td></tr>';
        console.error('加载任务失败:', error);
        lastTasksData = null;
    } finally {
        isLoadingTasks = false;
    }
}

function renderTasks(tasks) {
    const tbody = document.getElementById('tasks-tbody');
    // 使用 DocumentFragment 来减少重绘
    const fragment = document.createDocumentFragment();
    tasks.forEach(task => {
        const tr = document.createElement('tr');
        tr.dataset.status = task.status;
        // 转换状态为中文
        const statusMap = {
            'pending': '等待中',
            'downloading': '下载中',
            'renaming': '重命名中',
            'cover_uploading': '封面上传中',
            'completed': '已完成',
            'cover_upload_failed': '封面上传失败',
            'failed': '失败'
        };
        const statusText = statusMap[task.status] || task.status;
        // 进度保留一位小数
        const progress = Number(task.progress).toFixed(1);

        tr.innerHTML = `
            <td><span class="task-id">${task.task_id.substring(0, 8)}...</span></td>
            <td>${escapeHtml(task.title)}</td>
            <td><span class="status-${task.status}">${statusText}</span></td>
            <td>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: ${progress}%"></div>
                </div>
                <span>${progress}%</span>
            </td>
            <td>${escapeHtml(task.folder_name)}</td>
            <td>${formatDateTime(task.created_at)}</td>
            <td>
                <button class="btn-sm" onclick="deleteTask('${task.task_id}')">删除</button>
                ${task.status === 'failed' ? `<button class="btn-sm btn-primary" onclick="retryTask('${task.task_id}')">重试</button>` : ''}
            </td>
        `;
        fragment.appendChild(tr);
    });
    tbody.innerHTML = '';
    tbody.appendChild(fragment);
}

async function deleteTask(taskId) {
    if (!confirm('确定要删除这个任务吗？')) return;
    
    try {
        const response = await authenticatedFetch(`${API_BASE}/task/${taskId}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            loadTasks();
        } else {
            alert('删除失败');
        }
    } catch (error) {
        alert('删除失败: ' + error.message);
    }
}

async function retryTask(taskId) {
    try {
        const response = await authenticatedFetch(`${API_BASE}/task/${taskId}/retry`, {
            method: 'POST'
        });
        
        if (response.ok) {
            alert('任务已重新推送');
            loadTasks();
        } else {
            const data = await response.json();
            alert('重试失败: ' + (data.detail || '未知错误'));
        }
    } catch (error) {
        alert('重试失败: ' + error.message);
    }
}

async function deleteCompletedTasks() {
    if (!confirm('确定要删除所有已完成的任务吗？')) return;

    const btn = document.getElementById('delete-completed-tasks-btn');
    btn.disabled = true;
    btn.textContent = '删除中...';

    try {
        const response = await authenticatedFetch(`${API_BASE}/tasks/completed`, {
            method: 'DELETE'
        });

        if (response.ok) {
            const data = await response.json();
            alert(data.message);
            loadTasks();
        } else {
            const errorData = await response.json();
            alert('删除失败: ' + (errorData.detail || '未知错误'));
        }
    } catch (error) {
        alert('删除失败: ' + error.message);
    } finally {
        btn.disabled = false;
        btn.textContent = '删除已完成';
    }
}

async function deleteAllTasks() {
    if (!confirm('确定要删除所有任务吗？此操作不可撤销！')) return;

    const btn = document.getElementById('delete-all-tasks-btn');
    btn.disabled = true;
    btn.textContent = '删除中...';

    try {
        const response = await authenticatedFetch(`${API_BASE}/tasks/all`, {
            method: 'DELETE'
        });

        if (response.ok) {
            const data = await response.json();
            alert(data.message);
            loadTasks();
        } else {
            const errorData = await response.json();
            alert('删除失败: ' + (errorData.detail || '未知错误'));
        }
    } catch (error) {
        alert('删除失败: ' + error.message);
    } finally {
        btn.disabled = false;
        btn.textContent = '全部删除';
    }
}

// ========== 日志 ==========

function initLogsTab() {
    document.getElementById('clear-logs-btn').addEventListener('click', clearLogs);
    document.getElementById('export-logs-btn').addEventListener('click', exportLogs);
    document.getElementById('log-level-filter').addEventListener('change', loadLogs);
}

async function loadLogs() {
    const filter = document.getElementById('log-level-filter').value;
    const container = document.getElementById('logs-container');
    container.innerHTML = '<div class="loading">加载中...</div>';
    
    try {
        const url = filter === 'all' 
            ? `${API_BASE}/logs` 
            : `${API_BASE}/logs?level=${filter}`;
        
        const response = await authenticatedFetch(url);
        const data = await response.json();
        
        if (data.logs && data.logs.length > 0) {
            renderLogs(data.logs);
        } else {
            container.innerHTML = '<div class="empty-message">暂无日志</div>';
        }
    } catch (error) {
        container.innerHTML = '<div class="error-message">加载失败</div>';
    }
}

function renderLogs(logs) {
    const container = document.getElementById('logs-container');
    container.innerHTML = logs.map(log => `
        <div class="log-entry log-${log.level}">
            <span class="log-time">${log.time}</span>
            <span class="log-level">${log.level}</span>
            <span class="log-message">${escapeHtml(log.message)}</span>
        </div>
    `).join('');
}

function clearLogs() {
    if (!confirm('确定要清空所有日志吗？')) return;

    fetch(`${API_BASE}/logs`, {
        method: 'DELETE',
        credentials: 'include'
    })
    .then(response => {
        if (response.ok) {
            // 清空成功，重新加载日志
            loadLogs();
        } else {
            return response.json().then(data => {
                alert(`清空日志失败: ${data.detail || '未知错误'}`);
            });
        }
    })
    .catch(error => {
        console.error('清空日志失败:', error);
        alert('清空日志失败，请查看控制台');
    });
}

function exportLogs() {
    const container = document.getElementById('logs-container');
    const logs = Array.from(container.querySelectorAll('.log-entry'))
        .map(entry => entry.textContent).join('\n');
    
    const blob = new Blob([logs], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `logs_${new Date().toISOString().split('T')[0]}.txt`;
    a.click();
    URL.revokeObjectURL(url);
}

// ========== 设置 ==========

function switchAuthTab(authMethod) {
    // 移除所有标签页的激活状态
    document.querySelectorAll('.auth-tab').forEach(tab => {
        tab.classList.remove('active');
    });

    // 隐藏所有认证内容
    document.querySelectorAll('.auth-content').forEach(content => {
        content.style.display = 'none';
    });

    // 激活选中的标签页和内容
    const activeTab = document.querySelector(`.auth-tab[data-auth="${authMethod}"]`);
    const activeContent = document.getElementById(`${authMethod}-auth`);

    if (activeTab && activeContent) {
        activeTab.classList.add('active');
        activeContent.style.display = 'block';
    }
}

function initSettingsTab() {
    document.getElementById('settings-form').addEventListener('submit', saveSettings);
    document.getElementById('reset-settings-btn').addEventListener('click', resetSettings);
    document.getElementById('test-connection-btn').addEventListener('click', testConnection);
    document.getElementById('select-folder-btn').addEventListener('click', openFolderSelector);

    // 认证方式标签页切换
    document.querySelectorAll('.auth-tab').forEach(tab => {
        tab.addEventListener('click', (e) => {
            const authMethod = e.target.dataset.auth;
            switchAuthTab(authMethod);
        });
    });
}

// 配置加载状态，防止重复加载
let isLoadingConfig = false;

async function loadConfig() {
    // 如果正在加载，直接返回
    if (isLoadingConfig) {
        return;
    }
    
    isLoadingConfig = true;
    
    try {
        const response = await authenticatedFetch(`${API_BASE}/config`);
        
        if (!response.ok) {
            console.error('加载配置失败:', response.status, response.statusText);
            return;
        }
        
        const data = await response.json();
        
        document.getElementById('client-id').value = data.pan123.client_id || '';
        document.getElementById('client-secret').value = '';  // 不显示secret
        document.getElementById('username').value = data.pan123.username || '';
        document.getElementById('password').value = '';  // 不显示password
        
        // 设置认证方式
        if (data.pan123.username && data.pan123.password) {
            switchAuthTab('account');
        } else {
            switchAuthTab('client');
        }
        
        document.getElementById('root-dir-id').value = data.pan123.root_dir_id || 0;
        // document.getElementById('server-host').value = data.server.host || '127.0.0.1';  // HTML中已移除
        // document.getElementById('server-port').value = data.server.port || 8000;  // HTML中已移除
        document.getElementById('check-interval').value = data.monitoring.check_interval || 30;
        document.getElementById('download-timeout').value = data.monitoring.download_timeout || 3600;
    } catch (error) {
        console.error('加载配置失败:', error);
    } finally {
        isLoadingConfig = false;
    }
}

async function saveSettings(event) {
    event.preventDefault();

    // 根据激活的标签页确定认证方式
    const activeAuthTab = document.querySelector('.auth-tab.active');
    const authMethod = activeAuthTab ? activeAuthTab.dataset.auth : 'client';

    const formData = {
        pan123: {
            root_dir_id: parseInt(document.getElementById('root-dir-id').value) || 0
        },
        monitoring: {
            check_interval: parseInt(document.getElementById('check-interval').value) || 30,
            download_timeout: parseInt(document.getElementById('download-timeout').value) || 3600
        }
    };

    if (authMethod === 'client') {
        formData.pan123.client_id = document.getElementById('client-id').value.trim();
        formData.pan123.client_secret = document.getElementById('client-secret').value.trim();
        // 清空用户名密码
        formData.pan123.username = '';
        formData.pan123.password = '';
    } else {
        formData.pan123.username = document.getElementById('username').value.trim();
        formData.pan123.password = document.getElementById('password').value.trim();
        // 清空client信息
        formData.pan123.client_id = '';
        formData.pan123.client_secret = '';
    }
    
    try {
        console.log('开始保存配置:', formData);
        const response = await authenticatedFetch(`${API_BASE}/config`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(formData)
        });

        console.log('响应状态:', response.status);
        const data = await response.json();
        console.log('响应数据:', data);

        if (data.success) {
            alert('设置已保存');
        } else {
            alert('保存失败: ' + (data.detail || '未知错误'));
        }
    } catch (error) {
        console.error('保存配置出错:', error);
        alert('保存失败: ' + error.message);
    }
}

async function resetSettings() {
    if (!confirm('确定要重置为默认设置吗？这将清除您当前的所有配置！')) return;

    try {
        const response = await fetch('/api/config/reset', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            credentials: 'include'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || '重置失败');
        }

        const result = await response.json();
        if (result.success) {
            alert('配置已重置为默认值');
            // 重新加载页面以显示默认配置
            location.reload();
        } else {
            alert(result.message || '重置失败');
        }
    } catch (error) {
        console.error('重置配置出错:', error);
        alert('重置失败: ' + error.message);
    }
}

// ========== 工具函数 ==========

function formatDateTime(isoString) {
    const date = new Date(isoString);
    return date.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
    });
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ========== 测试123云盘连接 ==========

async function testConnection() {
    // 获取当前激活的认证方式
    const activeAuthTab = document.querySelector('.auth-tab.active');
    const authMethod = activeAuthTab ? activeAuthTab.dataset.auth : 'client';

    const testBtn = document.getElementById('test-connection-btn');
    const originalText = testBtn.textContent;
    testBtn.disabled = true;
    testBtn.textContent = '测试连接中...';

    try {
        let saveData = {};

        if (authMethod === 'client') {
            const clientId = document.getElementById('client-id').value.trim();
            const clientSecret = document.getElementById('client-secret').value.trim();

            if (!clientId || !clientSecret) {
                alert('请先填写 Client ID 和 Client Secret');
                testBtn.disabled = false;
                testBtn.textContent = originalText;
                return;
            }

            saveData.pan123 = {
                client_id: clientId,
                client_secret: clientSecret
            };
        } else {
            const username = document.getElementById('username').value.trim();
            const password = document.getElementById('password').value.trim();

            if (!username || !password) {
                alert('请先填写用户名和密码');
                testBtn.disabled = false;
                testBtn.textContent = originalText;
                return;
            }

            saveData.pan123 = {
                username: username,
                password: password
            };
        }

        // 先保存配置
        const saveResponse = await authenticatedFetch(`${API_BASE}/config`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(saveData)
        });

        if (!saveResponse.ok) {
            const responseData = await saveResponse.json();
            throw new Error('保存配置失败: ' + (responseData.detail || '未知错误'));
        }

        // 保存成功后，重新加载配置
        await loadConfig();

        // 获取token测试连接
        const tokenResponse = await authenticatedFetch(`${API_BASE}/auth/pan123/token`);
        const tokenData = await tokenResponse.json();

        if (tokenData.success) {
            testBtn.textContent = '获取成功！';
            setTimeout(() => {
                testBtn.textContent = originalText;
            }, 2000);
            const authTypeText = authMethod === 'client' ? 'Client ID/Secret' : '账号密码';
            alert(`Token获取成功！\n\n${authTypeText} 配置正确，Token有效期: ` + (tokenData.expired_at || '未知'));
        } else {
            alert('Token获取失败: ' + (tokenData.message || '未知错误'));
        }
    } catch (error) {
        alert('获取Token失败: ' + error.message);
    } finally {
        testBtn.disabled = false;
        if (testBtn.textContent === '测试连接中...') {
            testBtn.textContent = originalText;
        }
    }
}

// ========== 文件夹选择器 ==========

let currentParentId = 0;
let folderPathStack = [{ id: 0, name: '根目录' }];
let selectedFolderId = null;
let selectedFolderName = null;

function openFolderSelector() {
    document.getElementById('folder-selector-modal').classList.add('show');
    currentParentId = 0;
    folderPathStack = [{ id: 0, name: '根目录' }];
    selectedFolderId = null;
    selectedFolderName = null;
    updatePathDisplay();

    // 延迟加载文件夹列表，给服务器一些时间同步最新数据
    setTimeout(() => {
        loadFolders(0);
    }, 300);

    // 隐藏删除按钮
    const deleteBtn = document.getElementById('folder-delete-btn');
    if (deleteBtn) {
        deleteBtn.style.display = 'none';
    }
}

function closeFolderSelector() {
    document.getElementById('folder-selector-modal').classList.remove('show');
}

async function loadFolders(parentId) {
    const folderList = document.getElementById('folder-list');
    folderList.innerHTML = '<div class="loading">加载中...</div>';

    try {
        // 使用大 limit=10000 确保加载全部文件夹
        const response = await authenticatedFetch(`${API_BASE}/folders?parent_id=${parentId}&limit=10000`);
        const data = await response.json();

        if (data.success) {
            if (data.folders && data.folders.length > 0) {
                folderList.innerHTML = data.folders.map(folder => `
                    <div class="folder-item" data-id="${folder.file_id}" data-name="${escapeHtml(folder.filename)}" onclick="selectFolder(this)" ondblclick="enterFolder(${folder.file_id}, '${escapeHtml(folder.filename)}')">
                        <span class="folder-item-icon">📁</span>
                        <span class="folder-item-name">${escapeHtml(folder.filename)}</span>
                        <span class="folder-item-id">ID: ${folder.file_id}</span>
                    </div>
                `).join('');
            } else {
                folderList.innerHTML = '<div class="loading">此目录为空</div>';
            }
        } else {
            folderList.innerHTML = '<div class="loading">加载失败</div>';
        }
    } catch (error) {
        console.error('加载文件夹列表失败:', error);
        let errorMsg = error.message || '未知错误';

        // 检查是否是token过期错误
        if (errorMsg.includes('token is expired') || errorMsg.includes('Token 已过期') || errorMsg.includes('Access Token 已过期')) {
            errorMsg = 'Access Token 已过期，请在设置页面配置 Client ID 和 Client Secret 后点击"获取Token"';
        }

        folderList.innerHTML = '<div class="loading">加载失败: ' + errorMsg + '</div>';
    }
}

function selectFolder(element) {
    // 移除其他选中状态
    document.querySelectorAll('.folder-item').forEach(item => {
        item.classList.remove('selected');
    });

    // 添加选中状态
    element.classList.add('selected');
    selectedFolderId = parseInt(element.dataset.id);
    selectedFolderName = element.dataset.name;

    // 显示删除按钮
    const deleteBtn = document.getElementById('folder-delete-btn');
    if (deleteBtn) {
        deleteBtn.style.display = 'inline-block';
    }
}

function enterFolder(folderId, folderName) {
    currentParentId = folderId;
    folderPathStack.push({ id: folderId, name: folderName });
    updatePathDisplay();
    selectedFolderId = null;
    selectedFolderName = null;

    // 隐藏删除按钮
    const deleteBtn = document.getElementById('folder-delete-btn');
    if (deleteBtn) {
        deleteBtn.style.display = 'none';
    }

    // 延迟加载文件夹列表，给服务器一些时间同步最新数据
    setTimeout(() => {
        loadFolders(folderId);
    }, 300);
}

function goBackFolder() {
    if (folderPathStack.length > 1) {
        folderPathStack.pop();
        const prev = folderPathStack[folderPathStack.length - 1];
        currentParentId = prev.id;
        loadFolders(prev.id);
        updatePathDisplay();
        selectedFolderId = null;
        selectedFolderName = null;

        // 隐藏删除按钮
        const deleteBtn = document.getElementById('folder-delete-btn');
        if (deleteBtn) {
            deleteBtn.style.display = 'none';
        }
    }
}

function refreshFolderList() {
    // 显示刷新中状态
    const refreshBtn = document.getElementById('folder-refresh-btn');
    if (refreshBtn) {
        refreshBtn.disabled = true;
        refreshBtn.textContent = '刷新中...';
    }

    // 延迟加载文件夹列表，给服务器一些时间同步最新数据
    setTimeout(() => {
        loadFolders(currentParentId).finally(() => {
            if (refreshBtn) {
                refreshBtn.disabled = false;
                refreshBtn.textContent = '刷新';
            }
        });
    }, 300);
}

function updatePathDisplay() {
    const pathSpan = document.getElementById('current-path');
    if (pathSpan) {
        const path = folderPathStack.map(item => item.name).join(' / ');
        pathSpan.textContent = '/' + path;
    }
}

function confirmFolderSelection() {
    if (selectedFolderId !== null) {
        document.getElementById('root-dir-id').value = selectedFolderId;
        closeFolderSelector();
        showMessage(`已选择文件夹: ${selectedFolderName}`, 'success');
    } else {
        alert('请先选择一个文件夹');
    }
}

function showCreateFolderForm() {
    document.getElementById('create-folder-form').style.display = 'flex';
    document.getElementById('new-folder-name').focus();
}

function hideCreateFolderForm() {
    document.getElementById('create-folder-form').style.display = 'none';
    document.getElementById('new-folder-name').value = '';
}

async function createFolder() {
    const name = document.getElementById('new-folder-name').value.trim();
    if (!name) {
        alert('请输入文件夹名称');
        return;
    }

    try {
        const response = await authenticatedFetch(`${API_BASE}/folders`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, parent_id: currentParentId })
        });

        const data = await response.json();

        if (data.success) {
            showMessage('创建文件夹成功', 'success');
            hideCreateFolderForm();
            loadFolders(currentParentId);
        } else {
            alert('创建文件夹失败: ' + (data.detail || '未知错误'));
        }
    } catch (error) {
        alert('创建文件夹失败: ' + error.message);
    }
}

async function deleteSelectedFolder() {
    if (!selectedFolderId) {
        alert('请先选择要删除的文件夹');
        return;
    }

    if (!confirm(`确定要删除文件夹 "${selectedFolderName}" 吗？\n删除的文件将放入回收站。`)) {
        return;
    }

    try {
        const response = await authenticatedFetch(`${API_BASE}/folder/trash`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ file_ids: [selectedFolderId] })
        });

        const data = await response.json();

        if (data.success) {
            showMessage('文件夹已移至回收站', 'success');
            selectedFolderId = null;
            selectedFolderName = null;
            loadFolders(currentParentId);

            // 隐藏删除按钮
            const deleteBtn = document.getElementById('folder-delete-btn');
            if (deleteBtn) {
                deleteBtn.style.display = 'none';
            }
        } else {
            alert('删除文件夹失败: ' + (data.detail || '未知错误'));
        }
    } catch (error) {
        alert('删除文件夹失败: ' + error.message);
    }
}

// 显示消息提示
function showMessage(message, type = 'info') {
    alert(message);
}

// ========== 视频总览 ==========

function initVideosTab() {
    document.getElementById('refresh-videos-btn').addEventListener('click', () => loadVideos(true));
    document.getElementById('delete-all-videos-btn').addEventListener('click', deleteAllVideos);
    document.getElementById('video-search-btn').addEventListener('click', () => loadVideos(true));
    document.getElementById('video-search').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') loadVideos(true);
    });
    document.getElementById('video-time-filter-btn').addEventListener('click', showTimeFilterModal);

    // 排序选择器：记录初始值，只有真正改变时才触发
    const sortSelect = document.getElementById('video-sort');
    let lastSortValue = sortSelect.value;
    sortSelect.addEventListener('click', function() {
        // 记录点击时的值
        lastSortValue = this.value;
    });
    sortSelect.addEventListener('change', function() {
        // 只有当值真正改变时才加载
        if (this.value !== lastSortValue) {
            loadVideos(true);
            lastSortValue = this.value;
        }
    });

    document.getElementById('prev-page-btn').addEventListener('click', () => changePage(-1));
    document.getElementById('next-page-btn').addEventListener('click', () => changePage(1));
    document.getElementById('jump-page-btn').addEventListener('click', jumpToPage);
    document.getElementById('jump-page-input').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') jumpToPage();
    });

    // 页面大小选择器：记录初始值，只有真正改变时才触发
    const pageSizeSelect = document.getElementById('page-size-select');
    let lastPageSizeValue = pageSizeSelect.value;
    pageSizeSelect.addEventListener('click', function() {
        lastPageSizeValue = this.value;
    });
    pageSizeSelect.addEventListener('change', function() {
        if (this.value !== lastPageSizeValue) {
            loadVideos(true);
            lastPageSizeValue = this.value;
        }
    });

    // 导入导出按钮事件
    const exportBtn = document.getElementById('export-videos-btn');
    const importBtn = document.getElementById('import-videos-btn');
    if (exportBtn) {
        exportBtn.addEventListener('click', exportVideos);
    }
    if (importBtn) {
        importBtn.addEventListener('click', () => {
            const fileInput = document.createElement('input');
            fileInput.type = 'file';
            fileInput.accept = '.zip';
            fileInput.onchange = (e) => importVideos(e.target.files[0]);
            fileInput.click();
        });
    }

    // 时间筛选弹窗事件
    document.getElementById('close-time-filter-btn').addEventListener('click', hideTimeFilterModal);
    document.getElementById('confirm-time-filter-btn').addEventListener('click', applyTimeFilter);

    // 快捷时间选项点击事件
    document.querySelectorAll('.time-filter-option').forEach(option => {
        option.addEventListener('click', () => selectQuickTimeFilter(option));
    });

    // 初始化年份选项
    initYearOptions();

    // 检查是否为admin用户，控制删除按钮显示
    const username = localStorage.getItem('hanime_username');
    console.log('initVideosTab - username:', username);
    const deleteBtns = document.querySelectorAll('.admin-only');
    deleteBtns.forEach(btn => {
        btn.style.display = username === 'admin' ? 'inline-block' : 'none';
    });
}

// 视频加载状态，防止重复加载
let isLoadingVideos = false;

// 图片缓存状态（用于避免重复加载相同的图片）
let imageCache = new Map(); // 存储已加载的图片URL
const IMAGE_CACHE_DURATION = 30 * 60 * 1000; // 30分钟图片缓存

// 当前分页状态
let currentPage = 1;
let totalPages = 1;

async function loadVideos(resetPage = false) {
    if (isLoadingVideos) {
        return;
    }

    if (resetPage) {
        currentPage = 1;
        // 重置时清空缓存，需要重新加载所有视频
        allVideos = [];
        allVideosLoaded = false;
    }

    isLoadingVideos = true;

    const container = document.getElementById('videos-container');
    container.innerHTML = '<div class="empty-message">加载中...</div>';

    try {
        // 获取搜索、时间筛选、排序、分页参数
        const search = document.getElementById('video-search').value.trim();
        const sortValue = document.getElementById('video-sort').value;
        const [sort_by, sort_order] = sortValue.split('_');
        const page_size = parseInt(document.getElementById('page-size-select').value);

        // 构建URL参数
        const params = new URLSearchParams({
            page: currentPage,
            page_size: page_size,
            sort_by: sort_by,
            sort_order: sort_order
        });
        if (search) params.append('search', search);

        // 添加时间筛选参数
        if (currentTimeFilter.type === 'custom') {
            if (currentTimeFilter.year) {
                params.append('year', currentTimeFilter.year);
            }
            if (currentTimeFilter.month) {
                params.append('month', currentTimeFilter.month);
            }
        } else if (currentTimeFilter.type === 'quick') {
            params.append('time_range', currentTimeFilter.quick);
        }

        const response = await authenticatedFetch(`${API_BASE}/videos?${params}`);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();

        // 更新分页状态
        currentPage = data.page || 1;
        totalPages = data.total_pages || 1;

        // 更新分页UI
        updatePagination(data.total || 0, page_size);

        if (data.videos && data.videos.length > 0) {
            currentVideos = data.videos;
            renderVideos(data.videos);
        } else {
            currentVideos = [];
            container.innerHTML = '<div class="empty-message">暂无视频</div>';
        }
    } catch (error) {
        container.innerHTML = '<div class="empty-message">加载失败</div>';
        console.error('加载视频列表失败:', error);
    } finally {
        isLoadingVideos = false;
    }
}

// 加载所有视频（用于系列筛选等功能）
async function loadAllVideos() {
    if (allVideosLoaded) {
        return;
    }

    try {
        const response = await authenticatedFetch(`${API_BASE}/videos?page=1&page_size=10000`);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        allVideos = data.videos || [];
        allVideosLoaded = true;
    } catch (error) {
        console.error('加载所有视频失败:', error);
    }
}

// 切换页面
function changePage(delta) {
    const newPage = currentPage + delta;
    if (newPage >= 1 && newPage <= totalPages) {
        currentPage = newPage;
        loadVideos();
    }
}

// 跳转到指定页面
function jumpToPage() {
    const input = document.getElementById('jump-page-input');
    const targetPage = parseInt(input.value);

    if (isNaN(targetPage) || targetPage < 1 || targetPage > totalPages) {
        alert(`请输入有效的页码 (1-${totalPages})`);
        return;
    }

    currentPage = targetPage;
    input.value = '';
    loadVideos();
}

// 更新分页UI
function updatePagination(total, pageSize) {
    const pagination = document.getElementById('video-pagination');
    const pageInfo = document.getElementById('page-info');
    const prevBtn = document.getElementById('prev-page-btn');
    const nextBtn = document.getElementById('next-page-btn');

    if (total > 0) {
        pagination.style.display = 'flex';
        pageInfo.textContent = `第 ${currentPage} 页 / 共 ${totalPages} 页 (共 ${total} 条)`;
        prevBtn.disabled = currentPage <= 1;
        nextBtn.disabled = currentPage >= totalPages;
    } else {
        pagination.style.display = 'none';
    }
}

// ========== 时间筛选 ==========

// 初始化年份选项
function initYearOptions() {
    const yearSelect = document.getElementById('time-filter-year');
    const currentYear = new Date().getFullYear();
    const startYear = 1990;

    // 添加从1990年至今的所有年份
    for (let year = currentYear; year >= startYear; year--) {
        const option = document.createElement('option');
        option.value = year;
        option.textContent = year + '年';
        yearSelect.appendChild(option);
    }
}

// 显示时间筛选弹窗
function showTimeFilterModal() {
    document.getElementById('time-filter-modal').classList.add('show');

    // 重置快捷选项选中状态
    document.querySelectorAll('.time-filter-option').forEach(opt => {
        opt.classList.remove('selected');
    });

    // 根据当前筛选状态设置选中项
    if (currentTimeFilter.type === 'quick') {
        const selectedOption = document.querySelector(`.time-filter-option[data-filter="${currentTimeFilter.quick}"]`);
        if (selectedOption) selectedOption.classList.add('selected');
    }
}

// 隐藏时间筛选弹窗
function hideTimeFilterModal() {
    document.getElementById('time-filter-modal').classList.remove('show');
}

// 选择快捷时间筛选
function selectQuickTimeFilter(element) {
    // 如果当前选项已经选中，则取消选中
    if (element.classList.contains('selected')) {
        element.classList.remove('selected');
        return;
    }

    // 移除其他选项的选中状态
    document.querySelectorAll('.time-filter-option').forEach(opt => {
        opt.classList.remove('selected');
    });

    // 选中当前选项
    element.classList.add('selected');
}

// 应用时间筛选
function applyTimeFilter() {
    const selectedQuickOption = document.querySelector('.time-filter-option.selected');
    const year = document.getElementById('time-filter-year').value;
    const yearInput = document.getElementById('time-filter-year-input').value.trim();
    const month = document.getElementById('time-filter-month').value;

    // 使用手动输入的年份（如果有的话），否则使用下拉选择的年份
    const finalYear = yearInput || year;

    // 更新筛选状态
    if (selectedQuickOption) {
        currentTimeFilter.type = 'quick';
        currentTimeFilter.quick = selectedQuickOption.dataset.filter;
        currentTimeFilter.year = '';
        currentTimeFilter.month = '';
    } else if (finalYear || month) {
        currentTimeFilter.type = 'custom';
        currentTimeFilter.year = finalYear;
        currentTimeFilter.month = month;
        currentTimeFilter.quick = '';
    } else {
        currentTimeFilter.type = 'all';
        currentTimeFilter.year = '';
        currentTimeFilter.month = '';
        currentTimeFilter.quick = '';
    }

    hideTimeFilterModal();
    loadVideos(true);
}

// 存储所有视频数据（用于系列筛选等功能）
let allVideos = [];
// 当前显示的视频列表
let currentVideos = [];
// 当前筛选的系列名称
let currentSeriesFilter = null;
// 标记是否已加载所有视频
let allVideosLoaded = false;
// 选中的视频ID集合
let selectedVideos = new Set();
// 当前时间筛选状态
let currentTimeFilter = {
    type: 'all', // 'all', 'custom', 'quick'
    year: '',
    month: '',
    quick: '' // '24h', '2d', '1w', '1m', '3m'
};

function renderVideos(videos) {
    // 渲染当前分页的视频
    renderCurrentVideos(videos);
}

// 渲染当前视频列表
function renderCurrentVideos(videosToRender = null) {
    const container = document.getElementById('videos-container');
    const username = localStorage.getItem('hanime_username');
    const isAdmin = username === 'admin';

    // 如果有系列筛选，从所有视频中筛选；否则使用传入的视频或当前分页视频
    let displayVideos = currentSeriesFilter
        ? (allVideosLoaded ? allVideos.filter(video => (video.series_name || extractSeriesName(video.title)) === currentSeriesFilter) : [])
        : (videosToRender || currentVideos);

    // 是否显示勾选框（只有进入系列视频后显示）
    const showCheckbox = !!currentSeriesFilter;

    // 渲染视频卡片网格（直接输出，不包裹额外的div）
    let html = renderVideoCards(displayVideos, isAdmin, showCheckbox);

    // 如果有系列筛选，显示返回按钮和批量操作按钮
    if (currentSeriesFilter) {
        html = `
            <div style="margin-bottom: 20px; text-align: center; display: flex; gap: 10px; justify-content: center; align-items: center; flex-wrap: wrap;">
                <button class="btn btn-secondary" onclick="resetSeriesFilter()">
                    ← 返回所有视频
                </button>
                <button class="btn btn-primary" onclick="pushSelectedVideos()">
                    推送选中 (${selectedVideos.size})
                </button>
                <button class="btn btn-primary" onclick="pushAllSeriesVideos()">
                    全部推送
                </button>
                <button class="btn btn-secondary" onclick="selectAllVideos()">
                    全选
                </button>
                <button class="btn btn-secondary" onclick="deselectAllVideos()">
                    取消全选
                </button>
            </div>
            <div class="videos-grid">${html}</div>
        `;
    } else {
        html = `<div class="videos-grid">${html}</div>`;
    }

    container.innerHTML = html || '<div class="empty-message">暂无视频</div>';
}

// 提取系列名称（去除末尾序号）
function extractSeriesName(title) {
    // 去除末尾的数字（集数）
    return title.replace(/\s+\d+$/, '').trim();
}

// 格式化时长显示
function formatDuration(seconds) {
    if (!seconds || seconds <= 0) return '';
    const numSeconds = typeof seconds === 'string' ? parseInt(seconds) : seconds;
    if (isNaN(numSeconds) || numSeconds <= 0) return '';
    const hours = Math.floor(numSeconds / 3600);
    const minutes = Math.floor((numSeconds % 3600) / 60);
    const secs = numSeconds % 60;

    if (hours > 0) {
        return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    } else {
        return `${minutes}:${secs.toString().padStart(2, '0')}`;
    }
}

// 渲染视频卡片HTML
function renderVideoCards(videos, isAdmin, showCheckbox = false) {
    return videos.map(video => {
        const seriesName = video.series_name || extractSeriesName(video.title);

        // 图片缓存检查
        const cacheKey = video.cover_url;
        const now = Date.now();
        let coverHtml;

        if (video.cover_url && imageCache.has(cacheKey)) {
            const cacheEntry = imageCache.get(cacheKey);
            if (now - cacheEntry.timestamp < IMAGE_CACHE_DURATION) {
                // 使用缓存的图片
                coverHtml = `<img src="${escapeHtml(video.cover_url)}" alt="${escapeHtml(video.title)}" class="cached-image" />`;
            } else {
                // 缓存过期，移除并重新加载
                imageCache.delete(cacheKey);
                coverHtml = `<img src="${escapeHtml(video.cover_url)}" alt="${escapeHtml(video.title)}" onerror="this.style.display='none';this.parentElement.innerHTML='<div class=&quot;no-cover&quot;>🎬</div>'" onload="cacheImage('${escapeHtml(cacheKey)}')" />`;
            }
        } else {
            // 首次加载，添加缓存逻辑
            coverHtml = video.cover_url
                ? `<img src="${escapeHtml(video.cover_url)}" alt="${escapeHtml(video.title)}" onerror="this.style.display='none';this.parentElement.innerHTML='<div class=&quot;no-cover&quot;>🎬</div>'" onload="cacheImage('${escapeHtml(cacheKey)}')" />`
                : '<div class="no-cover">🎬</div>';
        }

        const deleteBtnHtml = isAdmin
            ? `<button class="btn btn-danger btn-sm video-btn" onclick="event.stopPropagation(); deleteVideo('${escapeHtml(video.video_id)}')">删除</button>`
            : '';

        const isSelected = selectedVideos.has(video.video_id);
        const checkedAttr = isSelected ? 'checked' : '';
        const selectedClass = isSelected ? 'video-card-selected' : '';
        const checkboxHtml = showCheckbox
            ? `<div class="video-card-checkbox">
                    <input type="checkbox" ${checkedAttr} onclick="event.stopPropagation(); toggleVideoSelection('${escapeHtml(video.video_id)}')">
                </div>`
            : '';

        // 卡片结构：封面+底部信息区+操作按钮
        return `
        <div class="video-card ${selectedClass}" data-video-id="${escapeHtml(video.video_id)}" onclick="${showCheckbox ? `toggleVideoSelection('${escapeHtml(video.video_id)}')` : `filterBySeries('${escapeHtml(seriesName)}')`}">
            ${checkboxHtml}
            <div class="video-cover">
                ${coverHtml}
            </div>
            <div class="video-info">
                <div class="video-title" title="${escapeHtml(video.title)}">${escapeHtml(video.title)}</div>
                <div class="video-meta-row">
                    <a class="video-id-link" href="https://hanime1.me/watch?v=${video.video_id}" target="_blank" onclick="event.stopPropagation()">ID: ${video.video_id.substring(0, 8)}</a>
                    ${video.duration ? `<span class="video-duration">${formatDuration(video.duration)}</span>` : ''}
                </div>
                <div class="video-meta-row">
                    <span class="video-pubdate">${video.created_at ? `发布时间: ${formatDate(video.created_at)}` : ''}</span>
                </div>
                <div class="video-actions-hover-wrap">
                    <div class="video-actions">
                        <button class="btn btn-primary btn-sm video-btn" onclick="event.stopPropagation(); pushVideoFromLibrary(${JSON.stringify(video).replace(/"/g, '&quot;')})">推送</button>
                        <button class="btn btn-secondary btn-sm video-btn" onclick="event.stopPropagation(); pushCoverToCloud('${escapeHtml(video.video_id)}', '${escapeHtml(video.title)}')">封面up</button>
                        ${deleteBtnHtml}
                    </div>
                </div>
            </div>
        </div>
        `;
    // 格式化发布时间
    function formatDate(dateStr) {
        if (!dateStr) return '';
        // 支持时间戳或 ISO 字符串
        let d = typeof dateStr === 'number' ? new Date(dateStr * 1000) : new Date(dateStr);
        if (isNaN(d.getTime())) return '';
        const y = d.getFullYear();
        const m = (d.getMonth() + 1).toString().padStart(2, '0');
        const day = d.getDate().toString().padStart(2, '0');
        return `${y}-${m}-${day}`;
    }
    }).join('');
}

// 按系列筛选视频
async function filterBySeries(seriesName) {
    currentSeriesFilter = seriesName;
    // 确保加载了所有视频用于筛选
    await loadAllVideos();
    renderCurrentVideos();
}

// 重置系列筛选
function resetSeriesFilter() {
    currentSeriesFilter = null;
    selectedVideos.clear();  // 清空选中
    renderCurrentVideos();
}

// 切换视频选中状态
function toggleVideoSelection(videoId) {
    if (selectedVideos.has(videoId)) {
        selectedVideos.delete(videoId);
    } else {
        selectedVideos.add(videoId);
    }
    renderCurrentVideos();  // 重新渲染以更新选中状态
}

// 全选当前系列的视频
function selectAllVideos() {
    const displayVideos = currentSeriesFilter
        ? (allVideosLoaded ? allVideos.filter(video => (video.series_name || extractSeriesName(video.title)) === currentSeriesFilter) : [])
        : currentVideos;
    displayVideos.forEach(video => selectedVideos.add(video.video_id));
    renderCurrentVideos();
}

// 取消全选
function deselectAllVideos() {
    selectedVideos.clear();
    renderCurrentVideos();
}

// 推送选中的视频（带2秒间隔）
async function pushSelectedVideos() {
    if (selectedVideos.size === 0) {
        alert('请先选择要推送的视频');
        return;
    }

    if (!confirm(`确定要推送 ${selectedVideos.size} 个视频吗？`)) {
        return;
    }

    const videosToPush = currentSeriesFilter
        ? (allVideosLoaded ? allVideos.filter(v => selectedVideos.has(v.video_id)) : [])
        : currentVideos.filter(v => selectedVideos.has(v.video_id));

    if (videosToPush.length === 0) {
        alert('没有可推送的视频');
        return;
    }

    let successCount = 0;
    let failCount = 0;

    for (let i = 0; i < videosToPush.length; i++) {
        const video = videosToPush[i];
        try {
            await pushSingleVideo(video, i + 1, videosToPush.length);
            successCount++;
        } catch (error) {
            console.error(`推送视频失败 [${i + 1}/${videosToPush.length}]:`, video.title, error);
            failCount++;
        }

        // 不是最后一个视频时，等待2秒
        if (i < videosToPush.length - 1) {
            await new Promise(resolve => setTimeout(resolve, 2000));
        }
    }

    alert(`推送完成！成功: ${successCount}, 失败: ${failCount}`);
    selectedVideos.clear();
    renderCurrentVideos();
}

// 推送当前系列的所有视频（带2秒间隔）
async function pushAllSeriesVideos() {
    const displayVideos = currentSeriesFilter
        ? (allVideosLoaded ? allVideos.filter(video => (video.series_name || extractSeriesName(video.title)) === currentSeriesFilter) : [])
        : currentVideos;

    if (displayVideos.length === 0) {
        alert('没有可推送的视频');
        return;
    }

    if (!confirm(`确定要推送当前系列的所有 ${displayVideos.length} 个视频吗？`)) {
        return;
    }

    let successCount = 0;
    let failCount = 0;

    for (let i = 0; i < displayVideos.length; i++) {
        const video = displayVideos[i];
        try {
            await pushSingleVideo(video, i + 1, displayVideos.length);
            successCount++;
        } catch (error) {
            console.error(`推送视频失败 [${i + 1}/${displayVideos.length}]:`, video.title, error);
            failCount++;
        }

        // 不是最后一个视频时，等待2秒
        if (i < displayVideos.length - 1) {
            await new Promise(resolve => setTimeout(resolve, 2000));
        }
    }

    alert(`推送完成！成功: ${successCount}, 失败: ${failCount}`);
    loadVideos();  // 刷新视频列表
}

// 推送单个视频（复用现有逻辑，但不弹出确认框）
async function pushSingleVideo(video, index, total) {
    console.log(`推送视频 [${index}/${total}]: ${video.title}`);

    try {
        // 使用系列名称作为文件夹名称（优先使用原日文标题）
        const folderName = video.series_name || video.title.replace(/\s+\d+$/, '').replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').trim();

        // 提取年份和月份
        let year = '未分类';
        let month = '01';
        if (video.created_at) {
            const d = typeof video.created_at === 'number' ? new Date(video.created_at * 1000) : new Date(video.created_at);
            if (!isNaN(d.getTime())) {
                year = d.getFullYear().toString();
                month = (d.getMonth() + 1).toString().padStart(2, '0');
            }
        }

        // 使用数据库中存储的 rename_name，如果没有则生成（与油猴脚本保持一致）
        let fileName = video.rename_name;
        if (!fileName) {
            const cleanTitle = video.title.replace(/\[.*?字幕.*?\]/g, '').trim();
            fileName = `[${year}${month}01]${cleanTitle}`;
        }

        // 先检查云盘中是否已存在该视频
        try {
            const checkResponse = await authenticatedFetch(`${API_BASE}/folder/check`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    folder_name: folderName,
                    video_title: fileName
                })
            });

            if (checkResponse.ok) {
                const checkData = await checkResponse.json();
                if (checkData.video_exists) {
                    console.log(`视频已存在于云盘中，跳过: ${video.title}`);
                    return;  // 跳过已存在的视频
                }
            }
        } catch (checkError) {
            console.warn('检查视频存在性失败，继续推送:', checkError.message);
            // 检查失败不阻止推送
        }

        // 推送下载（使用文件名作为title和rename_name参数）
        const response = await authenticatedFetch(`${API_BASE}/video/submit`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                video_id: video.video_id,
                title: fileName,
                download_url: video.local_url,
                folder_name: year,
                month_folder: month,
                rename_name: fileName
            })
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || '未知错误');
        }

        console.log(`推送成功: ${video.title}`);
    } catch (error) {
        throw error;
    }
}

// HTML转义函数
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

async function pushVideoFromLibrary(video) {
    if (!confirm(`确定要推送下载视频: ${video.title} 吗？`)) {
        return;
    }

    try {
        // 使用系列名称作为文件夹名称（优先使用原日文标题）
        const folderName = video.series_name || video.title.replace(/\s+\d+$/, '').replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').trim();

        // 提取年份和月份
        let year = '未分类';
        let month = '01';
        if (video.created_at) {
            const d = typeof video.created_at === 'number' ? new Date(video.created_at * 1000) : new Date(video.created_at);
            if (!isNaN(d.getTime())) {
                year = d.getFullYear().toString();
                month = (d.getMonth() + 1).toString().padStart(2, '0');
            }
        }

        // 使用数据库中存储的 rename_name，如果没有则生成（与油猴脚本保持一致）
        let fileName = video.rename_name;
        if (!fileName) {
            const cleanTitle = video.title.replace(/\[.*?字幕.*?\]/g, '').trim();
            fileName = `[${year}${month}01]${cleanTitle}`;
        }

        // 先检查云盘中是否已存在该视频
        try {
            const checkResponse = await authenticatedFetch(`${API_BASE}/folder/check`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    folder_name: folderName,
                    video_title: fileName
                })
            });

            if (checkResponse.ok) {
                const checkData = await checkResponse.json();
                if (checkData.video_exists) {
                    alert(`视频已存在于云盘中，无需重复下载：${video.title}`);
                    return;
                }
            }
        } catch (checkError) {
            console.warn('检查视频存在性失败，继续推送:', checkError.message);
            // 检查失败不阻止推送
        }

        // 推送下载（使用文件名作为title和rename_name参数）
        const response = await authenticatedFetch(`${API_BASE}/video/submit`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                video_id: video.video_id,
                title: fileName,
                download_url: video.local_url,
                folder_name: year,
                month_folder: month,
                rename_name: fileName
            })
        });

        if (response.ok) {
            const data = await response.json();
            alert('推送成功！任务ID: ' + data.task_id);
            loadVideos();  // 刷新视频列表
        } else {
            const errorData = await response.json();
            alert('推送失败: ' + (errorData.detail || '未知错误'));
        }
    } catch (error) {
        alert('推送失败: ' + error.message);
    }
}

async function deleteVideo(videoId) {
    if (!confirm('确定要删除这个视频吗？')) {
        return;
    }

    try {
        const response = await authenticatedFetch(`${API_BASE}/video/${videoId}`, {
            method: 'DELETE'
        });

        if (response.ok) {
            alert('删除成功');
            loadVideos();
        } else {
            alert('删除失败');
        }
    } catch (error) {
        alert('删除失败: ' + error.message);
    }
}

async function deleteAllVideos() {
    if (!confirm('确定要清空所有视频吗？此操作不可撤销！')) {
        return;
    }

    try {
        const response = await authenticatedFetch(`${API_BASE}/videos`);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();

        if (!data.videos || data.videos.length === 0) {
            alert('没有视频可删除');
            return;
        }

        let successCount = 0;
        let failCount = 0;

        for (const video of data.videos) {
            try {
                const delResponse = await authenticatedFetch(`${API_BASE}/video/${video.video_id}`, {
                    method: 'DELETE'
                });

                if (delResponse.ok) {
                    successCount++;
                } else {
                    failCount++;
                }
            } catch (error) {
                failCount++;
                console.error('删除视频失败:', error);
            }
        }

        alert(`清空完成！成功: ${successCount}, 失败: ${failCount}`);
        loadVideos();
    } catch (error) {
        alert('获取视频列表失败: ' + error.message);
    }
}

// 导出视频数据
async function exportVideos() {
    if (!confirm('确定要导出视频数据及封面吗？')) {
        return;
    }

    try {
        const response = await authenticatedFetch(`${API_BASE}/videos/export`);

        if (!response.ok) {
            const data = await response.json();
            alert('导出失败: ' + (data.detail || '未知错误'));
            return;
        }

        // 获取文件名
        const contentDisposition = response.headers.get('content-disposition');
        let filename = 'videos_export.zip';
        if (contentDisposition) {
            const filenameMatch = contentDisposition.match(/filename="(.+)"/);
            if (filenameMatch) {
                filename = filenameMatch[1];
            }
        }

        // 下载ZIP文件
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        alert(`导出成功！文件已下载: ${filename}`);
    } catch (error) {
        console.error('导出视频失败:', error);
        alert('导出失败: ' + error.message);
    }
}

// 导入视频数据
async function importVideos(file) {
    if (!file) {
        alert('请选择要导入的文件');
        return;
    }

    // 检查是否为ZIP文件
    if (!file.name.toLowerCase().endsWith('.zip')) {
        alert('请选择ZIP格式的导出文件');
        return;
    }

    const btn = document.getElementById('import-videos-btn');
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = '解压中...';

    try {
        // 使用JSZip解压文件
        const JSZip = window.JSZip;
        if (!JSZip) {
            alert('系统错误：缺少解压库，请刷新页面重试');
            btn.disabled = false;
            btn.textContent = originalText;
            return;
        }

        const zip = await JSZip.loadAsync(file);
        const metadataFile = zip.file('metadata.json');

        if (!metadataFile) {
            alert('文件格式错误：缺少metadata.json');
            btn.disabled = false;
            btn.textContent = originalText;
            return;
        }

        // 读取元数据
        const metadataText = await metadataFile.async('string');
        const metadata = JSON.parse(metadataText);
        const videos = metadata.videos || [];

        if (videos.length === 0) {
            alert('文件中没有视频数据');
            btn.disabled = false;
            btn.textContent = originalText;
            return;
        }

        btn.textContent = '处理封面中...';

        // 处理封面图片
        for (const video of videos) {
            const videoId = video.video_id;
            if (!videoId) continue;

            // 查找封面文件
            const coverExtensions = ['.jpg', '.png', '.webp'];
            for (const ext of coverExtensions) {
                const coverFile = zip.file(`covers/${videoId}${ext}`);
                if (coverFile) {
                    // 将封面图片转为base64
                    const coverData = await coverFile.async('base64');
                    video.cover_data = coverData;
                    break;
                }
            }
        }

        if (!confirm(`确定要导入 ${videos.length} 个视频吗？\n注意：已存在的视频会被跳过，不会覆盖。`)) {
            btn.disabled = false;
            btn.textContent = originalText;
            return;
        }

        btn.textContent = '导入中...';

        const response = await authenticatedFetch(`${API_BASE}/videos/import`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ videos })
        });

        const data = await response.json();

        if (data.success) {
            let msg = `导入成功！导入: ${data.imported}, 跳过: ${data.skipped}, 失败: ${data.failed}`;
            if (data.covers_imported > 0) {
                msg += `, 封面: ${data.covers_imported}`;
            }
            alert(msg);
            loadVideos();
        } else {
            alert('导入失败: ' + (data.detail || '未知错误'));
        }
    } catch (error) {
        console.error('导入视频失败:', error);
        alert('导入失败: ' + error.message);
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
}

// 推送封面到云端
async function pushCoverToCloud(videoId, title) {
    if (!confirm(`确定要推送视频 "${title}" 的封面到云端吗？`)) {
        return;
    }

    try {
        const response = await authenticatedFetch(`${API_BASE}/video/${videoId}/push-cover`, {
            method: 'POST'
        });

        const data = await response.json();

        if (response.ok && data.success) {
            alert('封面推送成功！');
            // 刷新视频列表
            loadVideos();
        } else {
            alert('封面推送失败: ' + (data.detail || data.message || '未知错误'));
        }
    } catch (error) {
        console.error('封面推送失败:', error);
        alert('封面推送失败: ' + error.message);
    }
}

// 显示通知消息
function showNotification(message, type = 'info') {
    // 创建通知元素
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;

    // 添加到页面
    document.body.appendChild(notification);

    // 显示动画
    setTimeout(() => {
        notification.classList.add('show');
    }, 10);

    // 自动隐藏
    setTimeout(() => {
        notification.classList.remove('show');
        setTimeout(() => {
            if (notification.parentNode) {
                notification.parentNode.removeChild(notification);
            }
        }, 300);
    }, 3000);
}

// 缓存图片加载状态
function cacheImage(imageUrl) {
    if (imageUrl && imageUrl !== 'undefined') {
        imageCache.set(imageUrl, {
            timestamp: Date.now(),
            loaded: true
        });
    }
}

// 切换认证方式显示
function toggleAuthMethod(method) {
    const clientAuth = document.getElementById('client-auth');
    const accountAuth = document.getElementById('account-auth');
    
    if (method === 'account') {
        clientAuth.style.display = 'none';
        accountAuth.style.display = 'block';
    } else {
        clientAuth.style.display = 'block';
        accountAuth.style.display = 'none';
    }
}
