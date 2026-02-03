// ==UserScript==
// @name         Hanime 123云盘下载助手
// @namespace    http://tampermonkey.net/
// @version      1.0.2
// @description  自动从 Hanime1.me 获取视频标题，推送视频信息到本地服务器，通过 123云盘离线下载
// @author       kanmu网络
// @match        https://hanime1.me/*
// @grant        GM_xmlhttpRequest
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_deleteValue
// @grant        GM_addStyle
// @connect      *
// ==/UserScript==

(function() {
    'use strict';

    // ==================== 默认配置 ====================
    const DEFAULT_CONFIG = {
        server: {
            baseUrl: 'http://127.0.0.1:16544',
            timeout: 20000
        },
        api_key: ''  // API密钥
    };

    // 加载配置
    function loadConfig() {
        const saved = GM_getValue('hanime_123_config', null);
        if (!saved) {
            return JSON.parse(JSON.stringify(DEFAULT_CONFIG));
        }
        return {
            server: {
                ...DEFAULT_CONFIG.server,
                ...(saved.server || {})
            },
            api_key: saved.api_key || DEFAULT_CONFIG.api_key
        };
    }

    // 保存配置
    function saveConfig(config) {
        GM_setValue('hanime_123_config', config);
    }

    let CONFIG = loadConfig();

    // ==================================================

    // 日志系统
    const logManager = {
        logs: [],
        maxLogs: 100,
        addLog: function(type, message) {
            const timestamp = new Date().toLocaleTimeString();
            const log = {
                type: type, // 'info', 'success', 'error', 'warning'
                message: message,
                timestamp: timestamp
            };
            this.logs.push(log);
            if (this.logs.length > this.maxLogs) {
                this.logs.shift();
            }
            this.updateUI();
        },
        updateUI: function() {
            const logContainer = document.getElementById('hanime-log-container');
            if (!logContainer) return;

            logContainer.innerHTML = '';
            this.logs.slice().reverse().forEach(log => {
                const logItem = document.createElement('div');
                logItem.className = `hanime-log-item hanime-log-${log.type}`;
                logItem.innerHTML = `
                    <span class="hanime-log-time">[${log.timestamp}]</span>
                    <span class="hanime-log-message">${this.escapeHtml(log.message)}</span>
                `;
                logContainer.appendChild(logItem);
            });
        },
        escapeHtml: function(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        },
        clear: function() {
            this.logs = [];
            this.updateUI();
        }
    };

    // 创建悬浮按钮（非播放页）
    function createFloatingButton() {
        // 检查是否已存在
        if (document.getElementById('hanime-download-button')) {
            return;
        }

        const button = document.createElement('button');
        button.id = 'hanime-download-button';
        button.innerHTML = '📥';
        button.title = 'Hanime 下载助手';

        document.body.appendChild(button);

        // 添加按钮样式
        addFloatingButtonStyles();

        // 绑定点击事件
        button.addEventListener('click', () => {
            createFloatingPanel();
            button.remove();
        });
    }

    // 添加悬浮按钮样式
    function addFloatingButtonStyles() {
        const style = document.createElement('style');
        style.textContent = `
            #hanime-download-button {
                position: fixed;
                top: 50%;
                right: 10px;
                transform: translateY(-50%);
                width: 50px;
                height: 50px;
                border-radius: 50%;
                background: linear-gradient(135deg, #ff6b6b 0%, #ff8e53 100%);
                border: none;
                color: white;
                font-size: 24px;
                cursor: pointer;
                box-shadow: 0 4px 15px rgba(255, 107, 107, 0.4);
                transition: all 0.3s ease;
                z-index: 99998;
                display: flex;
                align-items: center;
                justify-content: center;
            }

            #hanime-download-button:hover {
                transform: translateY(-50%) scale(1.1);
                box-shadow: 0 6px 20px rgba(255, 107, 107, 0.6);
            }

            #hanime-download-button:active {
                transform: translateY(-50%) scale(0.95);
            }
        `;
        document.head.appendChild(style);
    }

    // 创建悬浮弹窗
    function createFloatingPanel() {
        // 检查是否已存在
        if (document.getElementById('hanime-downloader-panel')) {
            return;
        }

        const panel = document.createElement('div');
        panel.id = 'hanime-downloader-panel';
        panel.innerHTML = `
            <div class="hanime-panel-header" id="hanime-panel-header">
                <span class="hanime-panel-title">Hanime 123云盘下载助手</span>
                <div class="hanime-panel-controls">
                    <button class="hanime-btn-icon" id="hanime-btn-settings" title="设置">⚙️</button>
                    <button class="hanime-btn-icon" id="hanime-btn-minimize" title="最小化">−</button>
                    <button class="hanime-btn-icon" id="hanime-btn-close" title="关闭">×</button>
                </div>
            </div>
            <div class="hanime-panel-content" id="hanime-panel-content">
                <div class="hanime-tab-container">
                    <button class="hanime-tab active" data-tab="download">下载</button>
                    <button class="hanime-tab" data-tab="cover">封面</button>
                    <button class="hanime-tab" data-tab="logs">日志</button>
                    <button class="hanime-tab" data-tab="settings">设置</button>
                </div>

                <div class="hanime-tab-content active" id="hanime-tab-download">
                    <div class="hanime-video-info" id="hanime-video-info">
                        <div class="hanime-info-item">
                            <label>视频标题:</label>
                            <span id="hanime-video-title">加载中...</span>
                        </div>
                        <div class="hanime-info-item">
                            <label class="hanime-checkbox-label">
                                <input type="checkbox" id="hanime-auto-create-folder" checked>
                                文件夹不存在时自动创建
                            </label>
                            <div class="hanime-info-hint">勾选后，如果找不到目标文件夹会自动创建</div>
                        </div>
                    </div>
                    <div class="hanime-download-controls">
                        <button class="hanime-btn hanime-btn-primary" id="hanime-btn-download">推送到服务器</button>
                        <button class="hanime-btn hanime-btn-secondary" id="hanime-btn-refresh">刷新信息</button>
                    </div>
                    <div class="hanime-progress" id="hanime-progress" style="display: none;">
                        <div class="hanime-progress-bar">
                            <div class="hanime-progress-fill" id="hanime-progress-fill"></div>
                        </div>
                        <div class="hanime-progress-text" id="hanime-progress-text">0%</div>
                    </div>
                </div>

                <div class="hanime-tab-content" id="hanime-tab-cover">
                    <div class="hanime-cover-id-list" id="hanime-cover-id-list" style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px;"></div>
                    <div class="hanime-cover-controls">
                        <button class="hanime-btn hanime-btn-primary" id="hanime-btn-get-ids">获取封面</button>
                        <button class="hanime-btn hanime-btn-secondary" id="hanime-btn-update-cover">补充封面</button>
                    </div>
                </div>

                <div class="hanime-tab-content" id="hanime-tab-logs">
                    <div class="hanime-log-controls">
                        <button class="hanime-btn hanime-btn-small" id="hanime-btn-clear-logs">清空日志</button>
                    </div>
                    <div class="hanime-log-container" id="hanime-log-container"></div>
                </div>

                <div class="hanime-tab-content" id="hanime-tab-settings">
                    <div class="hanime-settings-form">
                        <div class="hanime-setting-group">
                            <h3>本地服务器配置</h3>
                            <div class="hanime-setting-item">
                                <label>服务器地址:</label>
                                <input type="text" id="setting-server-url" value="${CONFIG.server.baseUrl}" placeholder="http://127.0.0.1:8000">
                            </div>
                            <div class="hanime-setting-item">
                                <label>API 密钥:</label>
                                <input type="text" id="setting-api-key" value="${CONFIG.api_key || ''}" placeholder="从管理后台登录后获取">
                            </div>
                            <div class="hanime-setting-item">
                                <label>请求超时 (毫秒):</label>
                                <input type="number" id="setting-server-timeout" value="${CONFIG.server.timeout}" placeholder="10000">
                            </div>
                        </div>



                        <div class="hanime-settings-actions">
                            <button class="hanime-btn hanime-btn-primary" id="hanime-btn-save-settings">保存设置</button>
                            <button class="hanime-btn hanime-btn-secondary" id="hanime-btn-reset-settings">重置默认</button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(panel);

        // 添加样式
        addPanelStyles();

        // 绑定事件
        bindPanelEvents();

        // 标记面板为已打开（用于导航后重建面板）
        try { GM_setValue('hanime_panel_open', true); } catch (e) { /* ignore */ }

        // 恢复面板位置（延迟一下确保DOM已渲染）
        setTimeout(() => {
            restorePanelPosition();
        }, 100);

        // 初始化
        refreshVideoInfo();
        logManager.addLog('info', '下载助手已启动');
    }

    // 添加弹窗样式
    function addPanelStyles() {
        const style = document.createElement('style');
        style.textContent = `
            #hanime-downloader-panel {
                position: fixed;
                top: 50%;
                right: 20px;
                transform: translateY(-50%);
                width: 400px;
                max-height: 80vh;
                background: #1e1e1e;
                border-radius: 8px;
                box-shadow: 0 4px 20px rgba(0,0,0,0.5);
                z-index: 99999;
                display: flex;
                flex-direction: column;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                color: #e5e5e5;
                overflow: hidden;
            }

            .hanime-panel-header {
                background: #2d2d2d;
                padding: 12px 16px;
                display: flex;
                justify-content: space-between;
                align-items: center;
                cursor: move;
                user-select: none;
            }

            .hanime-panel-title {
                font-weight: bold;
                font-size: 14px;
            }

            .hanime-panel-controls {
                display: flex;
                gap: 8px;
            }

            .hanime-btn-icon {
                background: transparent;
                border: none;
                color: #e5e5e5;
                cursor: pointer;
                font-size: 16px;
                width: 24px;
                height: 24px;
                display: flex;
                align-items: center;
                justify-content: center;
                border-radius: 4px;
                transition: background 0.2s;
            }

            .hanime-btn-icon:hover {
                background: #3d3d3d;
            }

            .hanime-panel-content {
                flex: 1;
                overflow: hidden;
                display: flex;
                flex-direction: column;
            }

            .hanime-tab-container {
                display: flex;
                background: #252525;
                border-bottom: 1px solid #3d3d3d;
            }

            .hanime-tab {
                flex: 1;
                padding: 10px;
                background: transparent;
                border: none;
                color: #999;
                cursor: pointer;
                font-size: 13px;
                transition: all 0.2s;
            }

            .hanime-tab:hover {
                background: #2d2d2d;
                color: #e5e5e5;
            }

            .hanime-tab.active {
                background: #1e1e1e;
                color: #ff6b6b;
                border-bottom: 2px solid #ff6b6b;
            }

            .hanime-tab-content {
                display: none;
                flex: 1;
                overflow-y: auto;
                padding: 16px;
            }

            .hanime-tab-content.active {
                display: flex;
                flex-direction: column;
            }

            #hanime-tab-download {
                min-height: 0;
            }

            .hanime-video-info {
                margin-bottom: 16px;
            }

            .hanime-info-item {
                margin-bottom: 12px;
                font-size: 13px;
            }

            .hanime-info-item label {
                color: #999;
                margin-right: 8px;
            }

            .hanime-info-item span {
                color: #e5e5e5;
                word-break: break-word;
            }

            .hanime-checkbox-label {
                display: flex;
                align-items: center;
                gap: 8px;
                color: #e5e5e5;
                font-weight: 500;
            }

            .hanime-checkbox-label input[type="checkbox"] {
                width: 16px;
                height: 16px;
            }

            .hanime-info-hint {
                font-size: 12px;
                color: #777;
            }

            .hanime-download-controls {
                display: flex;
                gap: 8px;
                margin-bottom: 16px;
            }

            .hanime-cover-controls {
                display: flex;
                gap: 8px;
                margin-bottom: 16px;
            }

            .hanime-btn {
                flex: 1;
                padding: 10px 16px;
                border: none;
                border-radius: 6px;
                cursor: pointer;
                font-size: 13px;
                font-weight: 500;
                transition: all 0.2s;
            }

            .hanime-btn-primary {
                background: #ff6b6b;
                color: white;
            }

            .hanime-btn-primary:hover {
                background: #ff5252;
            }

            .hanime-btn-primary:disabled {
                background: #666;
                cursor: not-allowed;
            }

            .hanime-btn-secondary {
                background: #3d3d3d;
                color: #e5e5e5;
            }

            .hanime-btn-secondary:hover {
                background: #4d4d4d;
            }

            .hanime-btn-small {
                padding: 6px 12px;
                font-size: 12px;
            }

            .hanime-progress {
                margin-top: 16px;
            }

            .hanime-progress-bar {
                width: 100%;
                height: 8px;
                background: #3d3d3d;
                border-radius: 4px;
                overflow: hidden;
                margin-bottom: 8px;
            }

            .hanime-progress-fill {
                height: 100%;
                background: #ff6b6b;
                transition: width 0.3s;
                width: 0%;
            }

            .hanime-progress-text {
                text-align: center;
                font-size: 12px;
                color: #999;
            }

            .hanime-log-container {
                flex: 1;
                overflow-y: auto;
                background: #151515;
                border-radius: 4px;
                padding: 8px;
                max-height: 400px;
                font-family: 'Courier New', monospace;
                font-size: 12px;
            }

            .hanime-log-item {
                margin-bottom: 4px;
                padding: 4px;
                border-radius: 2px;
            }

            .hanime-log-time {
                color: #666;
                margin-right: 8px;
            }

            .hanime-log-info .hanime-log-message {
                color: #4fc3f7;
            }

            .hanime-log-success .hanime-log-message {
                color: #66bb6a;
            }

            .hanime-log-error .hanime-log-message {
                color: #ef5350;
            }

            .hanime-log-warning .hanime-log-message {
                color: #ffa726;
            }

            .hanime-log-controls {
                margin-bottom: 8px;
            }

            .hanime-settings-form {
                display: flex;
                flex-direction: column;
                gap: 20px;
            }

            .hanime-setting-group h3 {
                margin: 0 0 12px 0;
                font-size: 14px;
                color: #ff6b6b;
            }

            .hanime-setting-item {
                margin-bottom: 12px;
            }

            .hanime-setting-item label {
                display: block;
                margin-bottom: 6px;
                font-size: 12px;
                color: #999;
            }

            .hanime-setting-item input[type="text"],
            .hanime-setting-item input[type="number"] {
                width: 100%;
                padding: 8px;
                background: #252525;
                border: 1px solid #3d3d3d;
                border-radius: 4px;
                color: #e5e5e5;
                font-size: 13px;
                box-sizing: border-box;
            }

            .hanime-setting-item input[type="text"]:focus,
            .hanime-setting-item input[type="number"]:focus {
                outline: none;
                border-color: #ff6b6b;
            }

            .hanime-setting-item input[type="checkbox"] {
                margin-right: 8px;
            }

            .hanime-settings-actions {
                display: flex;
                gap: 8px;
                margin-top: 16px;
            }

            #hanime-downloader-panel.minimized {
                height: auto !important;
                max-height: none !important;
                min-height: auto !important;
                transform: none !important;
                opacity: 0.5 !important;
            }

            #hanime-downloader-panel.minimized .hanime-panel-content {
                display: none !important;
            }

            #hanime-downloader-panel.minimized .hanime-panel-header {
                cursor: pointer;
            }

            #hanime-downloader-panel.minimized .hanime-panel-title {
                font-size: 13px;
            }
        `;
        document.head.appendChild(style);
    }

    // 绑定弹窗事件
    function bindPanelEvents() {
        // 标签切换
        document.querySelectorAll('.hanime-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                const tabName = tab.dataset.tab;
                document.querySelectorAll('.hanime-tab').forEach(t => t.classList.remove('active'));
                document.querySelectorAll('.hanime-tab-content').forEach(c => c.classList.remove('active'));
                tab.classList.add('active');
                document.getElementById(`hanime-tab-${tabName}`).classList.add('active');
            });
        });

        // 关闭按钮
        document.getElementById('hanime-btn-close').addEventListener('click', () => {
            try { GM_setValue('hanime_panel_open', false); } catch (e) { /* ignore */ }
            const p = document.getElementById('hanime-downloader-panel');
            if (p) p.remove();

            // 关闭后显示悬浮按钮
            createFloatingButton();
        });

        // 最小化按钮
        document.getElementById('hanime-btn-minimize').addEventListener('click', () => {
            const panel = document.getElementById('hanime-downloader-panel');
            panel.classList.toggle('minimized');
        });

        // 设置按钮
        document.getElementById('hanime-btn-settings').addEventListener('click', () => {
            document.querySelectorAll('.hanime-tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.hanime-tab-content').forEach(c => c.classList.remove('active'));
            document.querySelector('.hanime-tab[data-tab="settings"]').classList.add('active');
            document.getElementById('hanime-tab-settings').classList.add('active');
        });

        // 下载按钮
        document.getElementById('hanime-btn-download').addEventListener('click', () => {
            startDownloadProcess();
        });

        // 刷新按钮
        document.getElementById('hanime-btn-refresh').addEventListener('click', () => {
            refreshVideoInfo();
        });

        // 获取封面ID按钮
        document.getElementById('hanime-btn-get-ids').addEventListener('click', () => {
            getAllVideoIdsForCover();
        });
        // 补充封面按钮
        document.getElementById('hanime-btn-update-cover').addEventListener('click', () => {
            pushAllVideoIdsToServer();
        });

        // 清空日志
        document.getElementById('hanime-btn-clear-logs').addEventListener('click', () => {
            logManager.clear();
            logManager.addLog('info', '日志已清空');
        });

        // 保存设置
        document.getElementById('hanime-btn-save-settings').addEventListener('click', () => {
            saveSettings();
        });

        // 重置设置
        document.getElementById('hanime-btn-reset-settings').addEventListener('click', () => {
            if (confirm('确定要重置为默认设置吗？')) {
                resetSettings();
            }
        });

        // 拖拽功能
        let isDragging = false;
        let currentX, currentY, initialX, initialY;
        let offsetX, offsetY;
        const header = document.getElementById('hanime-panel-header');

        // 保存面板位置
        function savePanelPosition() {
            try {
                const panel = document.getElementById('hanime-downloader-panel');
                if (panel) {
                    const rect = panel.getBoundingClientRect();
                    const position = {
                        left: rect.left,
                        top: rect.top,
                        right: window.innerWidth - rect.right,
                        bottom: window.innerHeight - rect.bottom
                    };
                    GM_setValue('hanime_panel_position', JSON.stringify(position));
                }
            } catch (e) {
                console.warn('保存面板位置失败:', e);
            }
        }

        // 恢复面板位置
        function restorePanelPosition() {
            try {
                const panel = document.getElementById('hanime-downloader-panel');
                if (!panel) return;

                const saved = GM_getValue('hanime_panel_position', null);
                if (saved) {
                    const position = JSON.parse(saved);
                    // 检查位置是否在视窗内
                    const maxX = window.innerWidth - panel.offsetWidth;
                    const maxY = window.innerHeight - panel.offsetHeight;

                    if (position.left >= 0 && position.left <= maxX &&
                        position.top >= 0 && position.top <= maxY) {
                        panel.style.left = position.left + 'px';
                        panel.style.top = position.top + 'px';
                        panel.style.right = 'auto';
                        panel.style.bottom = 'auto';
                        panel.style.transform = 'none';
                        return;
                    }
                }

                // 如果没有保存的位置或位置无效，使用默认位置（右侧居中）
                panel.style.left = 'auto';
                panel.style.top = '50%';
                panel.style.right = '20px';
                panel.style.bottom = 'auto';
                panel.style.transform = 'translateY(-50%)';
            } catch (e) {
                console.warn('恢复面板位置失败:', e);
            }
        }

        header.addEventListener('mousedown', (e) => {
            const panel = document.getElementById('hanime-downloader-panel');
            const rect = panel.getBoundingClientRect();
            panel.style.left = rect.left + 'px';
            panel.style.top = rect.top + 'px';
            panel.style.right = 'auto';
            panel.style.bottom = 'auto';
            panel.style.transform = 'none';
            initialX = e.clientX;
            initialY = e.clientY;
            offsetX = e.clientX - rect.left;
            offsetY = e.clientY - rect.top;
            isDragging = true;
            e.preventDefault();
        });

        document.addEventListener('mousemove', (e) => {
            if (!isDragging) return;
            e.preventDefault();
            const panel = document.getElementById('hanime-downloader-panel');
            const newX = e.clientX - offsetX;
            const newY = e.clientY - offsetY;

            // 限制在视窗内
            const maxX = window.innerWidth - panel.offsetWidth;
            const maxY = window.innerHeight - panel.offsetHeight;

            panel.style.left = Math.max(0, Math.min(newX, maxX)) + 'px';
            panel.style.top = Math.max(0, Math.min(newY, maxY)) + 'px';
            panel.style.bottom = 'auto';
            panel.style.right = 'auto';
        });

        document.addEventListener('mouseup', () => {
            if (isDragging) {
                isDragging = false;
                // 拖拽结束时保存位置
                savePanelPosition();
            }
        });

        // 窗口大小改变时也保存位置
        window.addEventListener('resize', () => {
            savePanelPosition();
        });

        // 恢复面板位置
        restorePanelPosition();
    }

    // 获取所有视频卡片ID并横向展示
    function getAllVideoIdsForCover() {
        const idListDiv = document.getElementById('hanime-cover-id-list');
        idListDiv.innerHTML = '';
        let cards = [];
        // 1. 兼容原有卡片结构
        const playlistScroll = document.getElementById('playlist-scroll');
        if (playlistScroll) {
            cards = Array.from(playlistScroll.querySelectorAll('.related-watch-wrap.multiple-link-wrapper'));
        } else {
            cards = Array.from(document.querySelectorAll('.related-watch-wrap.multiple-link-wrapper'));
        }
        // 2. 兼容新结构 .home-rows-videos-div.search-videos
        const homeCards = Array.from(document.querySelectorAll('.home-rows-videos-div.search-videos'));
        // 合并所有卡片
        if (homeCards.length > 0) {
            cards = cards.concat(homeCards);
        }
        if (cards.length === 0) {
            logManager.addLog('error', '未找到任何视频卡片');
            return;
        }
        let foundCount = 0;
        for (const card of cards) {
            let videoId = null;
            let imgUrl = null;
            // 原有结构
            const linkEl = card.querySelector('a.overlay');
            if (linkEl) {
                const href = linkEl.getAttribute('href');
                videoId = extractVideoIdFromUrl(href);
            }
            // 新结构：img src 提取ID
            const imgEl = card.querySelector('img');
            if (!videoId && imgEl && imgEl.src) {
                videoId = extractVideoIdFromUrl(imgEl.src);
            }
            if (imgEl && imgEl.src) {
                imgUrl = imgEl.src;
            }
            // 只采集6位ID且img.src包含cover关键字
            if (
                videoId &&
                String(videoId).length === 6 &&
                imgUrl &&
                /cover/.test(imgUrl) &&
                /\.(jpg|jpeg|png)(\?|$)/i.test(imgUrl)
            ) {
                const idSpan = document.createElement('span');
                idSpan.textContent = videoId;
                idSpan.className = 'hanime-cover-id-item';
                idSpan.style.cssText = 'padding:4px 10px;border-radius:4px;background:#444;color:#fff;';
                idSpan.dataset.status = 'pending';
                idSpan.dataset.videoId = videoId;
                idListDiv.appendChild(idSpan);
                foundCount++;
            }
        }
        logManager.addLog('success', `已获取${foundCount}个视频ID`);
    }

    // 批量推送所有ID到服务器，变色显示校验结果
    async function pushAllVideoIdsToServer() {
        const idListDiv = document.getElementById('hanime-cover-id-list');
        const spans = Array.from(idListDiv.querySelectorAll('.hanime-cover-id-item'));
        if (spans.length === 0) {
            logManager.addLog('error', '请先点击“获取封面”获取视频ID');
            return;
        }
        let successCount = 0;
        let failCount = 0;
        for (const span of spans) {
            const videoId = span.dataset.videoId;
            let coverData = '';
            // 获取图片base64数据
            let card = null;
            // 1. 原有结构
            card = Array.from(document.querySelectorAll('.related-watch-wrap.multiple-link-wrapper')).find(card => {
                const linkEl = card.querySelector('a.overlay');
                if (linkEl) {
                    const href = linkEl.getAttribute('href');
                    return extractVideoIdFromUrl(href) === videoId;
                }
                return false;
            });
            // 2. 新结构
            if (!card) {
                card = Array.from(document.querySelectorAll('.home-rows-videos-div.search-videos')).find(card => {
                    const imgEl = card.querySelector('img');
                    if (imgEl && imgEl.src) {
                        return extractVideoIdFromUrl(imgEl.src) === videoId;
                    }
                    return false;
                });
            }
            if (card) {
                const imgEl = card.querySelector('img');
                if (imgEl && imgEl.src) {
                    // 将图片转为base64
                    try {
                        coverData = await getImageBase64(imgEl.src);
                    } catch (e) {
                        logManager.addLog('warning', `图片转base64失败: ${imgEl.src}`);
                    }
                }
            }
            if (!coverData) {
                logManager.addLog('warning', `未能获取视频ID ${videoId} 的图片数据`);
            }
            try {
                // 只根据服务端返回 success 字段变色
                const url = `${CONFIG.server.baseUrl}/api/video/update-cover`;
                const requestData = { video_id: videoId, cover_data: coverData };
                await new Promise((resolve, reject) => {
                    const headers = { 'Content-Type': 'application/json' };
                    if (CONFIG.api_key && CONFIG.api_key.trim()) {
                        headers['X-API-Key'] = CONFIG.api_key.trim();
                    }
                    GM_xmlhttpRequest({
                        method: 'POST',
                        url: url,
                        headers: headers,
                        data: JSON.stringify(requestData),
                        timeout: CONFIG.server.timeout,
                        onload: function(response) {
                            try {
                                const data = JSON.parse(response.responseText);
                                if (response.status === 200 && data.success) {
                                    span.style.background = '#4caf50';
                                    span.style.color = '#fff';
                                    span.dataset.status = 'success';
                                    successCount++;
                                } else {
                                    span.style.background = '#f44336';
                                    span.style.color = '#fff';
                                    span.dataset.status = 'fail';
                                    failCount++;
                                }
                                resolve(data);
                            } catch (e) {
                                span.style.background = '#f44336';
                                span.style.color = '#fff';
                                span.dataset.status = 'fail';
                                failCount++;
                                resolve({success:false});
                            }
                        },
                        onerror: function() {
                            span.style.background = '#f44336';
                            span.style.color = '#fff';
                            span.dataset.status = 'fail';
                            failCount++;
                            resolve({success:false});
                        },
                        ontimeout: function() {
                            span.style.background = '#f44336';
                            span.style.color = '#fff';
                            span.dataset.status = 'fail';
                            failCount++;
                            resolve({success:false});
                        }
                    });
                });
            } catch (error) {
                span.style.background = '#f44336';
                span.style.color = '#fff';
                span.dataset.status = 'fail';
                failCount++;
            }

        // 工具函数：将图片URL转为base64
        function getImageBase64(url) {
            return new Promise((resolve, reject) => {
                const img = new window.Image();
                img.crossOrigin = 'Anonymous';
                img.onload = function() {
                    try {
                        const canvas = document.createElement('canvas');
                        canvas.width = img.width;
                        canvas.height = img.height;
                        const ctx = canvas.getContext('2d');
                        ctx.drawImage(img, 0, 0, img.width, img.height);
                        const dataURL = canvas.toDataURL('image/jpeg');
                        resolve(dataURL);
                    } catch (e) {
                        reject(e);
                    }
                };
                img.onerror = function(e) {
                    reject(e);
                };
                img.src = url;
            });
        }
        }
        logManager.addLog('info', `补充封面完成，存在: ${successCount}，不存在: ${failCount}`);
    }

    // 刷新视频信息
    function refreshVideoInfo() {
        const title = getVideoTitle();

        const titleEl = document.getElementById('hanime-video-title');
        if (titleEl) {
            if (title) {
                titleEl.textContent = title;
            } else {
                titleEl.innerHTML = '<span style="color: #ff6b6b;">未找到标题 (点击推送时可手动输入)</span>';
            }
        }

        // 根据是否为播放页启用/禁用下载按钮并展示提示
        try {
            const downloadBtn = document.getElementById('hanime-btn-download');
            const panel = document.getElementById('hanime-downloader-panel');
            const isWatch = isWatchPage();
            if (downloadBtn) downloadBtn.disabled = !isWatch;

            if (panel) {
                const prev = panel.dataset.isWatch || '';
                const now = isWatch ? '1' : '0';
                if (prev !== now) {
                    panel.dataset.isWatch = now;
                    if (!isWatch) {
                        logManager.addLog('warning', '当前页面不是播放页，推送按钮已禁用');
                    } else {
                        logManager.addLog('info', '检测到播放页，推送按钮已启用');
                    }
                }

                let hint = document.getElementById('hanime-page-hint');
                const infoArea = document.getElementById('hanime-video-info') || document.getElementById('hanime-panel-content');
                if (!isWatch) {
                    if (!hint && infoArea) {
                        hint = document.createElement('div');
                        hint.id = 'hanime-page-hint';
                        hint.style.cssText = 'margin-top:8px;color:#ffb3b3;font-size:12px;';
                        hint.textContent = '当前页面不是播放页。请打开视频播放页面以启用推送功能。';
                        infoArea.appendChild(hint);
                    } else if (hint) {
                        hint.style.display = 'block';
                    }
                } else {
                    if (hint) hint.style.display = 'none';
                }
            }
        } catch (e) {
            console.warn('刷新视频信息时更新按钮状态失败', e);
        }

        if (title) {
            logManager.addLog('success', `已获取视频标题: ${title}`);
        } else {
            logManager.addLog('warning', '无法获取视频标题');
        }
    }

    // 保存设置
    function saveSettings() {
        CONFIG = {
            server: {
                baseUrl: document.getElementById('setting-server-url').value.trim(),
                timeout: parseInt(document.getElementById('setting-server-timeout').value) || 10000
            },
            api_key: document.getElementById('setting-api-key').value.trim()
        };
        saveConfig(CONFIG);
        logManager.addLog('success', '设置已保存');
    }

    // 重置设置
    function resetSettings() {
        CONFIG = JSON.parse(JSON.stringify(DEFAULT_CONFIG));
        saveConfig(CONFIG);
        document.getElementById('setting-server-url').value = CONFIG.server.baseUrl;
        document.getElementById('setting-api-key').value = CONFIG.api_key || '';
        document.getElementById('setting-server-timeout').value = CONFIG.server.timeout;
        logManager.addLog('info', '设置已重置为默认值');
    }

    // 更新进度
    function updateProgress(current, total) {
        const progress = document.getElementById('hanime-progress');
        const progressFill = document.getElementById('hanime-progress-fill');
        const progressText = document.getElementById('hanime-progress-text');

        if (total > 0) {
            const percent = Math.round((current / total) * 100);
            progress.style.display = 'block';
            progressFill.style.width = percent + '%';
            progressText.textContent = `${current}/${total} (${percent}%)`;
        } else {
            progress.style.display = 'none';
        }
    }

    // 获取当前播放的视频标题（直接从h3元素获取日文标题）
    function getVideoTitle() {
        // 直接从h3元素获取日文标题
        const h3Element = document.querySelector('h3#shareBtn-title');
        if (h3Element) {
            let title = h3Element.textContent.trim();
            // 去除 [中文字幕] 等标记
            title = title.replace(/\[.*?字幕.*?\]/g, '').trim();
            return title;
        }

        // 备选方案：查找包含 [中文字幕] 的元素
        const elementsWithSubtitle = document.querySelectorAll('*');
        for (const element of elementsWithSubtitle) {
            const text = element.textContent || '';
            if (text.includes('[中文字幕]')) {
                // 获取包含 [中文字幕] 的文本，并去除字幕标记
                let title = text.trim();
                title = title.replace(/\[.*?字幕.*?\]/g, '').trim();
                return title;
            }
        }

        // 如果h3不存在，使用页面标题作为后备
        const h4Elements = document.querySelectorAll('h4');
        for (const h4 of h4Elements) {
            const style = h4.getAttribute('style') || '';
            if (style.includes('margin-top: 0px') &&
                style.includes('line-height: 20px') &&
                style.includes('font-size: 14px')) {
                return h4.textContent.trim();
            }
        }
        return null;
    }

    // 判断当前页面是否为播放页（watch），用于启用/禁用下载按钮
    function isWatchPage() {
        try {
            const path = window.location.pathname || '';
            const search = window.location.search || '';
            if (path.indexOf('/watch') !== -1) return true;
            if (/[?&]v=\d+/.test(search)) return true;
            return false;
        } catch (e) {
            return false;
        }
    }

    // 获取当前视频的下载链接
    async function getCurrentVideoDownloadLink() {
        // 方法1: 从 preload 链接获取
        const preloadLink = document.querySelector('link[rel="preload"][as="video"]');
        if (preloadLink && preloadLink.href) {
            return preloadLink.href;
        }

        // 方法2: 从 video 标签的 source 获取
        const videoSource = document.querySelector('video source');
        if (videoSource && videoSource.src) {
            return videoSource.src;
        }

        // 方法3: 从 video 标签直接获取
        const videoElement = document.querySelector('video');
        if (videoElement && videoElement.src) {
            return videoElement.src;
        }

        // 方法4: 尝试从页面中查找所有可能的视频链接
        const allLinks = document.querySelectorAll('link[href*=".mp4"], link[href*=".m3u8"]');
        if (allLinks.length > 0) {
            return allLinks[0].href;
        }

        throw new Error('无法从当前页面获取视频下载链接');
    }

    // 获取当前视频的时长（秒）
    function getVideoDuration() {
        // 方法1: 从video元素获取
        const videoElement = document.querySelector('video');
        if (videoElement && videoElement.duration && !isNaN(videoElement.duration)) {
            return Math.floor(videoElement.duration);
        }

        // 方法2: 从页面文本中查找时长信息
        const durationPatterns = [
            /(\d{1,2}):(\d{2}):(\d{2})/,  // HH:MM:SS
            /(\d{1,2}):(\d{2})/,          // MM:SS
            /(\d+)\s*秒/,                 // X秒
            /(\d+)\s*分钟/,               // X分钟
            /时长[：:]\s*(\d+)[：:]\s*(\d+)[：:]\s*(\d+)/,  // 时长: HH:MM:SS
            /时长[：:]\s*(\d+)[：:]\s*(\d+)/,               // 时长: MM:SS
            /duration[：:]\s*(\d+)[：:]\s*(\d+)[：:]\s*(\d+)/i
        ];

        const textContent = document.body.textContent || '';
        for (const pattern of durationPatterns) {
            const match = textContent.match(pattern);
            if (match) {
                if (match.length === 4) { // HH:MM:SS
                    const hours = parseInt(match[1]);
                    const minutes = parseInt(match[2]);
                    const seconds = parseInt(match[3]);
                    return hours * 3600 + minutes * 60 + seconds;
                } else if (match.length === 3) { // MM:SS
                    const minutes = parseInt(match[1]);
                    const seconds = parseInt(match[2]);
                    return minutes * 60 + seconds;
                } else if (match.length === 2) { // X秒 或 X分钟
                    const value = parseInt(match[1]);
                    if (pattern.source.includes('秒')) {
                        return value;
                    } else if (pattern.source.includes('分钟')) {
                        return value * 60;
                    }
                }
            }
        }

        return null; // 无法获取时长
    }

    // 从URL中提取视频ID
    function extractVideoIdFromUrl(url) {
        if (!url) return null;

        // 方法1: 匹配 v=数字 的模式（查询参数）
        const vMatch = url.match(/[?&]v=(\d+)/);
        if (vMatch) {
            return vMatch[1];
        }

        // 方法2: 匹配URL路径中的数字（通常是视频ID）
        // 例如: /watch/110650 或 /video/110650 或 /110650
        const pathMatch = url.match(/\/(\d{4,8})(?:\/|$|\?)/);
        if (pathMatch) {
            return pathMatch[1];
        }

        // 方法3: 从封面URL中提取（如果URL包含cover关键词）
        // 例如: https://vdownload.hembed.com/image/cover/110650.jpg
        if (url.includes('cover') || url.includes('image')) {
            const coverMatch = url.match(/\/(\d{4,8})\./);
            if (coverMatch) {
                return coverMatch[1];
            }
        }

        // 方法4: 匹配其他可能的数字模式
        // 查找URL中连续的5-8位数字（视频ID通常是这个范围）
        const numberMatch = url.match(/(\d{5,8})/);
        if (numberMatch) {
            return numberMatch[1];
        }

        return null;
    }

    // 获取当前视频的封面URL
    function getVideoCover() {
        // 方法1: 从 meta 标签获取
        const metaImage = document.querySelector('meta[property="og:image"]');
        if (metaImage && metaImage.content) {
            return metaImage.content;
        }

        // 方法2: 从页面中查找封面图片
        const coverSelectors = [
            'img[src*="cover"]',
            'img[alt*="封面"]',
            'img[alt*="cover"]',
            '.video-cover img',
            '.cover img',
            '.thumbnail img'
        ];

        for (const selector of coverSelectors) {
            const img = document.querySelector(selector);
            if (img && img.src) {
                return img.src;
            }
        }

        // 方法3: 从播放列表中获取当前视频的封面
        const playlistScroll = document.getElementById('playlist-scroll');
        if (playlistScroll) {
            const currentVideoId = extractVideoIdFromUrl(window.location.href);
            if (currentVideoId) {
                const videoCards = playlistScroll.querySelectorAll('.related-watch-wrap.multiple-link-wrapper');
                for (const card of videoCards) {
                    const linkEl = card.querySelector('a.overlay');
                    if (linkEl) {
                        const href = linkEl.getAttribute('href');
                        if (href && href.includes(`v=${currentVideoId}`)) {
                            const imgEl = card.querySelector('img');
                            if (imgEl && imgEl.src) {
                                return imgEl.src;
                            }
                        }
                    }
                }
            }
        }

        return null; // 无法获取封面
    }

    // 从视频标题中提取系列名称
    function getVideoSeriesName(title) {
        if (!title) return null;

        // 移除常见的标记和时间戳
        let cleanTitle = title.replace(/^\[\d{8}\]/, '').trim(); // 移除 [20231229] 格式的时间戳
        cleanTitle = cleanTitle.replace(/\[.*?\]/g, '').trim(); // 移除其他中括号内容

        // 尝试提取系列名称（通常是数字前的部分）
        // 例如: "甜蜜惡作劇 1" -> "甜蜜惡作劇"
        const seriesMatch = cleanTitle.match(/^(.+?)\s+\d+$/);
        if (seriesMatch) {
            return seriesMatch[1].trim();
        }

        // 如果没有数字后缀，可能是单集视频，返回null
        return null;
    }

    // 发送带API密钥的请求
    function apiRequest(method, url, data = null, onsuccess = null, onerror = null) {
        const headers = {
            'Content-Type': 'application/json'
        };

        // 添加API密钥（如果已配置）
        if (CONFIG.api_key && CONFIG.api_key.trim()) {
            headers['X-API-Key'] = CONFIG.api_key.trim();
        }

        GM_xmlhttpRequest({
            method: method,
            url: url,
            headers: headers,
            data: data ? JSON.stringify(data) : null,
            timeout: CONFIG.server.timeout,
            onload: function(response) {
                try {
                    if (response.status === 401) {
                        // 未授权
                        logManager.addLog('error', 'API密钥无效或已过期，请重新登录');
                        if (onerror) {
                            onerror(new Error('未授权，请检查API密钥'));
                        }
                        return;
                    }
                    if (onsuccess) {
                        onsuccess(response);
                    }
                } catch (e) {
                    logManager.addLog('error', `解析响应失败: ${e.message}`);
                    if (onerror) {
                        onerror(e);
                    }
                }
            },
            onerror: function() {
                logManager.addLog('error', `请求失败: ${url}`);
                if (onerror) {
                    onerror(new Error(`网络错误: 无法连接到服务器`));
                }
            },
            ontimeout: function() {
                logManager.addLog('error', `请求超时: ${url}`);
                if (onerror) {
                    onerror(new Error(`请求超时: 无法在 ${CONFIG.server.timeout}ms 内连接到服务器`));
                }
            }
        });
    }

    // 检查云盘文件夹是否存在（支持嵌套文件夹）
    async function checkCloudFolder(folderPath) {
        try {
            const parts = folderPath.split('/');
            let currentParentId = null;

            // 逐级检查文件夹
            for (let i = 0; i < parts.length; i++) {
                const folderName = parts[i];
                const url = `${CONFIG.server.baseUrl}/api/folder/check`;
                const requestData = {
                    folder_name: folderName,
                    parent_dir_id: currentParentId
                };

                const result = await new Promise((resolve, reject) => {
                    GM_xmlhttpRequest({
                        method: 'POST',
                        url: url,
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        data: JSON.stringify(requestData),
                        timeout: CONFIG.server.timeout,
                        onload: function(response) {
                            try {
                                const data = JSON.parse(response.responseText);
                                if (response.status === 200) {
                                    resolve(data);
                                } else {
                                    // 如果检查失败，返回默认结果（文件夹不存在）
                                    resolve({
                                        folder_exists: false,
                                        folder_id: null,
                                        root_dir_id: null,
                                        files: []
                                    });
                                }
                            } catch (e) {
                                // 解析失败，返回默认结果
                                resolve({
                                    folder_exists: false,
                                    folder_id: null,
                                    root_dir_id: null,
                                    files: []
                                });
                            }
                        },
                        onerror: function(error) {
                            // 网络错误，返回默认结果
                            resolve({
                                folder_exists: false,
                                folder_id: null,
                                root_dir_id: null,
                                files: []
                            });
                        },
                        ontimeout: function() {
                            // 超时，返回默认结果
                            resolve({
                                folder_exists: false,
                                folder_id: null,
                                root_dir_id: null,
                                files: []
                            });
                        }
                    });
                });

                // 如果是最后一级，返回完整结果
                if (i === parts.length - 1) {
                    return result;
                }

                // 如果中间级别的文件夹不存在，返回不存在
                if (!result.folder_exists) {
                    return {
                        folder_exists: false,
                        folder_id: null,
                        root_dir_id: result.root_dir_id,
                        files: []
                    };
                }

                // 更新父目录ID，继续检查下一级
                currentParentId = result.folder_id;
            }

            // 不应该到达这里
            return {
                folder_exists: false,
                folder_id: null,
                root_dir_id: null,
                files: []
            };
        } catch (error) {
            console.error('检查文件夹失败:', error);
            throw error;
        }
    }

    // 获取视频发布时间
    function getVideoReleaseTime() {
        // 方法1: 从视频描述面板获取（根据用户提供的HTML结构）
        const descPanel = document.querySelector('.video-description-panel');
        if (descPanel) {
            // 查找包含"观看次数"的元素
            const textContent = descPanel.textContent || '';
            // 格式: "观看次数：117.8万次 2018-12-29"
            const dateMatch = textContent.match(/(\d{4})-(\d{2})-(\d{2})/);
            if (dateMatch) {
                return `${dateMatch[1]}${dateMatch[2]}${dateMatch[3]}`; // 返回 YYYYMMDD 格式
            }
        }

        // 方法2: 从页面其他位置查找日期
        const dateElements = document.querySelectorAll('*');
        for (const el of dateElements) {
            const text = el.textContent || '';
            const dateMatch = text.match(/(\d{4})-(\d{2})-(\d{2})/);
            if (dateMatch && text.match(/观看|发布|upload/i)) {
                return `${dateMatch[1]}${dateMatch[2]}${dateMatch[3]}`;
            }
        }

        return null;
    }

    // 保存视频信息到服务器
    async function saveVideoInfo(videoId, title, coverUrl, duration, downloadUrl = null, seriesName = null, releaseTime = null, renameName = null) {
        const url = `${CONFIG.server.baseUrl}/api/video/save`;

        // 不再推送封面，等待后续补充
        const requestData = {
            video_id: videoId,
            title: title,
            series_name: seriesName,
            duration: duration ? duration.toString() : null,
            local_url: downloadUrl,
            release_time: releaseTime,
            rename_name: renameName
        };

        return new Promise((resolve, reject) => {
            GM_xmlhttpRequest({
                method: 'POST',
                url: url,
                headers: {
                    'Content-Type': 'application/json'
                },
                data: JSON.stringify(requestData),
                timeout: CONFIG.server.timeout,
                onload: function(response) {
                    try {
                        const data = JSON.parse(response.responseText);
                        if (response.status === 200 && data.success) {
                            resolve(data);
                        } else {
                            // 保存失败不影响主流程，仅记录日志
                            console.warn('保存视频信息失败:', data.message);
                            resolve(data);
                        }
                    } catch (e) {
                        console.warn('解析视频信息保存响应失败:', e);
                        resolve({success: false}); // 失败但不阻塞
                    }
                },
                onerror: function(error) {
                    console.warn('保存视频信息网络错误:', error);
                    resolve({success: false}); // 失败但不阻塞
                },
                ontimeout: function() {
                    console.warn('保存视频信息超时');
                    resolve({success: false}); // 失败但不阻塞
                }
            });
        });
    }

    // 推送单个视频到本地服务器
    async function pushVideoToServer(videoId, title, downloadUrl) {
        // 验证参数
        if (!downloadUrl || downloadUrl.trim() === '') {
            throw new Error('download_url 不能为空');
        }
        if (!videoId) {
            throw new Error('video_id 不能为空');
        }
        // 优先使用页面 h3 日文标题作为推送的 video title（回退到传入的 title）
        const titleFromH3 = getVideoTitle();
        const pushTitle = titleFromH3 || title;
        if (!pushTitle) {
            throw new Error('title 不能为空');
        }

        // 获取视频发布时间
        const releaseTime = getVideoReleaseTime();

        if (!releaseTime) {
            throw new Error('无法获取视频发布时间');
        }

        // 解析年月
        const year = releaseTime.substring(0, 4);
        const month = releaseTime.substring(4, 6);

        logManager.addLog('info', `视频发布时间: ${releaseTime} (${year}年${month}月)`);

        // 从h3元素获取标题（去除 [中文字幕] 等标记），用于生成文件名和作为推送的 video title
        const h3Title = pushTitle;
        const cleanTitle = (h3Title || '').replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').trim();
        // 生成文件名: [发布时间]+h3标题
        const fileName = `[${releaseTime}]${cleanTitle}`;

        logManager.addLog('info', `文件名: ${fileName}`);

        // 检查目标月份文件夹中是否已存在相同视频
        try {
            logManager.addLog('info', `检查文件夹 ${year}/${month} 中是否已存在视频...`);
            const checkResult = await checkCloudFolder(`${year}/${month}`);

            if (checkResult.folder_exists && checkResult.files && checkResult.files.length > 0) {
                // 检查文件名是否匹配（去除扩展名比较）
                const existingFileNames = checkResult.files.map(file => file.filename.toLowerCase().replace(/\.[^/.]+$/, ""));
                const targetFileName = fileName.toLowerCase();

                // 精确匹配检查
                if (existingFileNames.includes(targetFileName)) {
                    logManager.addLog('warning', `视频已存在: ${fileName}，跳过推送`);
                    throw new Error(`视频已存在: ${fileName}`);
                }

                // 模糊匹配检查（去除特殊字符后比较）
                const normalizedTarget = targetFileName.replace(/[\[\]]/g, '').replace(/[^\w\u4e00-\u9fff]/g, '');
                for (const existing of existingFileNames) {
                    const normalizedExisting = existing.replace(/[\[\]]/g, '').replace(/[^\w\u4e00-\u9fff]/g, '');
                    if (normalizedExisting === normalizedTarget) {
                        logManager.addLog('warning', `视频已存在（模糊匹配）: ${fileName}，跳过推送`);
                        throw new Error(`视频已存在（相似文件）: ${fileName}`);
                    }
                }
            } else if (!checkResult.folder_exists) {
                logManager.addLog('info', `目标文件夹 ${year}/${month} 不存在，将自动创建`);
            }

            logManager.addLog('info', '视频不存在，开始推送...');
        } catch (checkError) {
            if (checkError.message.includes('视频已存在')) {
                throw checkError; // 重新抛出已存在的错误
            }
            // 检查失败时继续推送（网络错误等）
            logManager.addLog('warning', `检查视频存在性失败: ${checkError.message}，继续推送`);
        }

        const url = `${CONFIG.server.baseUrl}/api/video/submit`;

        const requestData = {
            video_id: videoId,
            title: pushTitle,  // 使用 h3 日文标题作为 video title（用于记录/显示），回退到页面标题
            download_url: downloadUrl.trim(),
            folder_name: year,  // 年份文件夹
            month_folder: month,  // 月份文件夹（新字段）
            rename_name: fileName  // 重命名文件名（保存到数据库）
        };

        logManager.addLog('info', `正在推送视频到服务器: ${fileName}`);

        return new Promise((resolve, reject) => {
            GM_xmlhttpRequest({
                method: 'POST',
                url: url,
                headers: {
                    'Content-Type': 'application/json'
                },
                data: JSON.stringify(requestData),
                timeout: CONFIG.server.timeout,
                onload: async function(response) {
                    try {
                        const data = JSON.parse(response.responseText);
                        if (response.status === 200 && data.success) {
                            logManager.addLog('success', `推送成功! 任务ID: ${data.task_id}`);
                            resolve(data);
                        } else {
                            const errorMessage = data.message || `服务器返回错误: ${response.status}`;
                            reject(new Error(errorMessage));
                        }
                    } catch (e) {
                        reject(new Error(`解析服务器响应失败: ${response.responseText}`));
                    }
                },
                onerror: function(error) {
                    reject(new Error(`网络错误: 无法连接到本地服务器 ${CONFIG.server.baseUrl}`));
                },
                ontimeout: function() {
                    reject(new Error(`请求超时: 无法在 ${CONFIG.server.timeout}ms 内连接到服务器`));
                }
            });
        });
    }

    // 开始下载推送流程
    async function startDownloadProcess() {
        const downloadBtn = document.getElementById('hanime-btn-download');
        if (downloadBtn) downloadBtn.disabled = true;

        try {
            // 下载当前视频
            await processSingleVideo();
        } catch (error) {
            logManager.addLog('error', error.message);
        } finally {
            if (downloadBtn) downloadBtn.disabled = false;
        }
    }

    // 处理单个视频
    async function processSingleVideo() {
        try {
            let videoId = extractVideoIdFromUrl(window.location.href);
            let title = getVideoTitle();
            const downloadUrl = await getCurrentVideoDownloadLink();
            const duration = getVideoDuration();

            // 如果从页面URL中无法获取视频ID，尝试从当前URL提取
            if (!videoId) {
                throw new Error('无法获取视频ID');
            }

            // 如果无法获取标题，显示手动输入对话框
            if (!title) {
                logManager.addLog('warning', '无法自动获取视频标题，显示手动输入对话框...');
                try {
                    title = await showTitleInputDialog();
                    logManager.addLog('success', `用户输入标题: ${title}`);
                } catch (dialogError) {
                    throw new Error('用户取消输入标题');
                }
            }

            // 先保存视频信息到webui后台（不含封面）
            try {
                const seriesName = getVideoSeriesName(title);
                const releaseTime = getVideoReleaseTime();
                const cleanTitle = title.replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').trim();
                const fileName = `[${releaseTime}]${cleanTitle}`;
                await saveVideoInfo(videoId, title, null, duration, downloadUrl, seriesName, releaseTime, fileName);
                logManager.addLog('success', '视频信息已保存到后台');
            } catch (saveError) {
                logManager.addLog('warning', `保存视频信息失败: ${saveError.message}`);
                // 保存失败不影响下载流程
            }

            // 然后推送视频到下载服务器
            try {
                const pushResult = await pushVideoToServer(videoId, title, downloadUrl);
                logManager.addLog('success', '视频已推送到服务器');
            } catch (pushError) {
                if (pushError.message.includes('视频已存在')) {
                    logManager.addLog('warning', pushError.message);
                } else {
                    throw pushError; // 其他错误重新抛出
                }
            }

        } catch (error) {
            throw error;
        }
    }

     // HTML转义辅助函数
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // 页面加载完成后初始化
    function init() {
        // 等待页面加载完成
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', init);
            return;
        }

        // 延迟一下确保页面元素加载完成
        setTimeout(() => {
            // 检查是否为播放页
            if (isWatchPage()) {
                // 播放页：直接显示完整面板，使用更短的延迟
                setTimeout(() => createFloatingPanel(), 100);
            } else {
                // 非播放页：只显示悬浮按钮
                createFloatingButton();
            }

            // 如果之前标记面板为打开，则恢复
            try {
                const wasOpen = GM_getValue('hanime_panel_open', false);
                if (!document.getElementById('hanime-downloader-panel') && wasOpen && isWatchPage()) {
                    createFloatingPanel();
                }
            } catch (e) {
                // ignore
            }
        }, 1000);
    }

    // 监听页面导航，重建面板
    let lastUrl = location.href;
    new MutationObserver(() => {
        const url = location.href;
        if (url !== lastUrl) {
            lastUrl = url;
            setTimeout(() => {
                // 移除现有的面板和按钮
                const panel = document.getElementById('hanime-downloader-panel');
                const button = document.getElementById('hanime-download-button');
                if (panel) panel.remove();
                if (button) button.remove();

                // 根据当前页面类型重新创建UI
                if (isWatchPage()) {
                    // 播放页：显示完整面板
                    const panelOpen = GM_getValue('hanime_panel_open', false);
                    if (panelOpen || !document.getElementById('hanime-downloader-panel')) {
                        createFloatingPanel();
                    }
                } else {
                    // 非播放页：显示悬浮按钮
                    createFloatingButton();
                }
            }, 500);
        }
    }).observe(document, { subtree: true, childList: true });

    // 显示手动输入标题的对话框
    function showTitleInputDialog() {
        return new Promise((resolve, reject) => {
            // 检查是否已存在对话框
            if (document.getElementById('hanime-title-dialog')) {
                document.getElementById('hanime-title-dialog').remove();
            }

            // 临时降低主界面的z-index，确保弹窗在最顶层
            const mainPanel = document.getElementById('hanime-downloader-panel');
            let originalZIndex = null;
            if (mainPanel) {
                originalZIndex = mainPanel.style.zIndex;
                mainPanel.style.zIndex = '99998';
            }

            // 创建对话框
            const dialog = document.createElement('div');
            dialog.id = 'hanime-title-dialog';
            dialog.innerHTML = `
                <div class="hanime-dialog-overlay">
                    <div class="hanime-dialog-content">
                        <div class="hanime-dialog-header">
                            <h3>请输入视频标题</h3>
                            <button class="hanime-dialog-close" id="hanime-dialog-close">×</button>
                        </div>
                        <div class="hanime-dialog-body">
                            <p>脚本无法自动获取视频标题，请手动输入：</p>
                            <input type="text" id="hanime-title-input" placeholder="请输入日文标题..." style="width: 100%; padding: 8px; margin: 10px 0; border: 1px solid #ccc; border-radius: 4px;">
                            <div class="hanime-dialog-buttons">
                                <button class="hanime-btn hanime-btn-secondary" id="hanime-dialog-cancel">取消</button>
                                <button class="hanime-btn hanime-btn-primary" id="hanime-dialog-confirm">确定</button>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            document.body.appendChild(dialog);

            // 添加对话框样式
            const style = document.createElement('style');
            style.textContent = `
                .hanime-dialog-overlay {
                    position: fixed !important;
                    top: 0 !important;
                    left: 0 !important;
                    right: 0 !important;
                    bottom: 0 !important;
                    background: rgba(0, 0, 0, 0.7) !important;
                    display: flex !important;
                    align-items: center !important;
                    justify-content: center !important;
                    z-index: 999999 !important;
                }
                .hanime-dialog-content {
                    background: #1e1e1e;
                    border-radius: 8px;
                    padding: 0;
                    max-width: 400px;
                    width: 90%;
                    color: #e5e5e5;
                    box-shadow: 0 4px 20px rgba(0,0,0,0.5);
                }
                .hanime-dialog-header {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    padding: 16px;
                    border-bottom: 1px solid #3d3d3d;
                }
                .hanime-dialog-header h3 {
                    margin: 0;
                    font-size: 16px;
                    color: #ff6b6b;
                }
                .hanime-dialog-close {
                    background: transparent;
                    border: none;
                    color: #e5e5e5;
                    font-size: 20px;
                    cursor: pointer;
                    padding: 0;
                    width: 24px;
                    height: 24px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                }
                .hanime-dialog-body {
                    padding: 16px;
                }
                .hanime-dialog-body p {
                    margin: 0 0 10px 0;
                    color: #999;
                    font-size: 14px;
                }
                .hanime-dialog-buttons {
                    display: flex;
                    gap: 8px;
                    justify-content: flex-end;
                    margin-top: 16px;
                }
            `;
            document.head.appendChild(style);

            // 绑定事件
            const input = document.getElementById('hanime-title-input');
            const confirmBtn = document.getElementById('hanime-dialog-confirm');
            const cancelBtn = document.getElementById('hanime-dialog-cancel');
            const closeBtn = document.getElementById('hanime-dialog-close');

            const closeDialog = () => {
                dialog.remove();
                style.remove();
                // 恢复主界面的z-index
                if (mainPanel && originalZIndex !== null) {
                    mainPanel.style.zIndex = originalZIndex;
                }
                reject(new Error('用户取消输入'));
            };

            const confirmDialog = () => {
                const title = input.value.trim();
                if (!title) {
                    alert('请输入标题');
                    return;
                }
                dialog.remove();
                style.remove();
                // 恢复主界面的z-index
                if (mainPanel && originalZIndex !== null) {
                    mainPanel.style.zIndex = originalZIndex;
                }
                resolve(title);
            };

            confirmBtn.addEventListener('click', confirmDialog);
            cancelBtn.addEventListener('click', closeDialog);
            closeBtn.addEventListener('click', closeDialog);

            // 回车确认
            input.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    confirmDialog();
                }
            });

            // 自动聚焦输入框
            setTimeout(() => input.focus(), 100);
        });
    }

    // 启动
    init();

})();
