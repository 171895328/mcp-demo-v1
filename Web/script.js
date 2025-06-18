// 全局变量
let socket;
let isConnected = false;
let isProcessing = false;
let currentAIMessageId = null;
let typingIndicator = null;
let showReasoning = true; // 默认显示思考过程
let darkMode = false; // 默认浅色模式
let isSidebarVisible = true; // 大屏幕默认显示侧边栏
let userRequestedDisconnect = false; // 跟踪用户是否主动请求断开
let lastContextId = null
let currentReasoningMessageDiv = null
// 添加一个计数器或会话ID来区分不同的用户消息
let conversationCounter = 0;
let currentSessionId = null;

// 页面加载时执行
document.addEventListener('DOMContentLoaded', () => {
    // 初始化WebSocket连接
    connectWebSocket();
    
    // 监听理性思考开关
    const reasoningToggle = document.getElementById('show-reasoning');
    reasoningToggle.addEventListener('change', function() {
        showReasoning = this.checked;
        
        // 控制现有推理消息的显示/隐藏
        const reasoningMessages = document.querySelectorAll('.message-reasoning');
        reasoningMessages.forEach(msg => {
            msg.style.display = showReasoning ? 'flex' : 'none';
        });
        
        // 保存用户设置
        localStorage.setItem('showReasoning', showReasoning);
    });
    
    // 监听深色模式开关
    const darkModeToggle = document.getElementById('dark-mode');
    darkModeToggle.addEventListener('change', function() {
        darkMode = this.checked;
        document.body.classList.toggle('dark-theme', darkMode);
        localStorage.setItem('darkMode', darkMode);
    });
    
    // 加载用户设置
    if (localStorage.getItem('showReasoning') !== null) {
        showReasoning = localStorage.getItem('showReasoning') === 'true';
        reasoningToggle.checked = showReasoning;
    }
    
    if (localStorage.getItem('darkMode') !== null) {
        darkMode = localStorage.getItem('darkMode') === 'true';
        darkModeToggle.checked = darkMode;
        document.body.classList.toggle('dark-theme', darkMode);
    }
    
    // 移动端侧边栏切换
    const toggleSidebarBtn = document.getElementById('toggle-sidebar');
    toggleSidebarBtn.addEventListener('click', toggleSidebar);
    
    // 新对话按钮
    const newChatBtn = document.getElementById('new-chat-btn');
    newChatBtn.addEventListener('click', resetConversation);
    
    // 清空对话按钮
    const clearBtn = document.getElementById('clear-btn');
    clearBtn.addEventListener('click', clearConversation);
    
    // 发送按钮
    const sendButton = document.getElementById('send-button');
    sendButton.addEventListener('click', sendMessage);
    
    // 命令按钮
    const commandButtons = document.querySelectorAll('.command-btn');
    commandButtons.forEach(btn => {
        btn.addEventListener('click', function() {
            const command = this.getAttribute('data-command');
            if (command) {
                sendCommand(command);
            }
        });
    });
    
    // 示例按钮
    const exampleButtons = document.querySelectorAll('.example-btn');
    exampleButtons.forEach(btn => {
        btn.addEventListener('click', function() {
            const example = this.getAttribute('data-example');
            if (example) {
                fillExample(example);
            }
        });
    });
    
    // 监听输入框变化，以启用/禁用发送按钮
    const userInput = document.getElementById('user-input');
    userInput.addEventListener('input', function() {
        sendButton.disabled = this.value.trim() === '';
        
        // 自动调整文本区域高度
        this.style.height = 'auto';
        const newHeight = Math.min(this.scrollHeight, 200);
        this.style.height = newHeight + 'px';
    });
    
    // 监听输入框键盘事件
    userInput.addEventListener('keydown', function(event) {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            sendMessage();
        }
    });
    
    // 监听窗口大小变化，自动切换侧边栏可见性
    window.addEventListener('resize', handleResize);
    handleResize(); // 初始化时执行一次
    
    // 添加欢迎消息
    if (document.querySelector('.chat-messages').children.length === 0) {
        // 显示欢迎界面（由HTML提供，无需添加）
        document.querySelector('.welcome-screen').style.display = 'flex';
    } else {
        document.querySelector('.welcome-screen').style.display = 'none';
    }
});

// 处理窗口大小变化
function handleResize() {
    const sidebar = document.querySelector('.sidebar');
    const isMobile = window.innerWidth <= 900;
    
    if (isMobile) {
        sidebar.classList.remove('show');
        isSidebarVisible = false;
    } else {
        sidebar.classList.add('show');
        isSidebarVisible = true;
    }
}

// 切换侧边栏显示/隐藏
function toggleSidebar() {
    const sidebar = document.querySelector('.sidebar');
    isSidebarVisible = !isSidebarVisible;
    
    if (isSidebarVisible) {
        sidebar.classList.add('show');
    } else {
        sidebar.classList.remove('show');
    }
}

// 重置对话
function resetConversation() {
    if (isConnected) {
        sendCommand('reset');
        clearMessages();
        document.querySelector('.welcome-screen').style.display = 'flex';
    } else {
        addSystemMessage("未连接到服务器，无法重置对话。");
    }
}

// 清空对话
function clearConversation() {
    clearMessages();
    document.querySelector('.welcome-screen').style.display = 'flex';
}

// 清空消息
function clearMessages() {
    const chatMessages = document.getElementById('chat-messages');
    chatMessages.innerHTML = '';
    currentAIMessageId = null;
}

// 连接WebSocket
function connectWebSocket() {
    try {
        // 直接使用硬编码的WebSocket地址
        socket = new WebSocket(`ws://127.0.0.1:5000/ws`);
        
        socket.onopen = function(e) {
            console.log("WebSocket 连接已建立");
            isConnected = true;
            updateConnectionStatus();
        };

        socket.onmessage = function(event) {
            console.log("收到消息:", event.data); // 添加这行调试代码
            handleMessage(event.data);
        };
        socket.onclose = function(event) {
            console.log("WebSocket 连接已关闭", event);
            isConnected = false;
            updateConnectionStatus();
            
            // 只有在不是用户主动请求断开的情况下才重连
            if (!userRequestedDisconnect) {
                console.log("5秒后尝试重连...");
                setTimeout(connectWebSocket, 5000);
            } else {
                console.log("用户已请求断开连接，不会自动重连");
            }
        };

        socket.onerror = function(error) {
            console.error("WebSocket 错误:", error);
            isConnected = false;
            updateConnectionStatus();
        };
    } catch (error) {
        console.error("创建 WebSocket 连接失败:", error);
        updateConnectionStatus();
    }
}

// 更新连接状态显示
function updateConnectionStatus() {
    const statusElement = document.getElementById('connection-status');
    if (isConnected) {
        statusElement.innerHTML = '<i class="fas fa-circle"></i><span>已连接</span>';
        statusElement.className = "connection-status connected";
    } else {
        statusElement.innerHTML = '<i class="fas fa-circle"></i><span>未连接</span>';
        statusElement.className = "connection-status disconnected";
    }
}

// 处理接收到的消息


// 处理内容消息
// 处理接收到的消息
function handleMessage(data) {
    try {
        const message = JSON.parse(data);

        // 隐藏欢迎屏幕
        document.querySelector('.welcome-screen').style.display = 'none';

        switch (message.type) {
            case "content":
                handleContentMessage(message);
                break;
            case "reasoning":
                if (showReasoning) {
                    handleReasoningMessage(message);
                }
                break;
            case "tool_result":
                handleToolResultMessage(message);
                break;
            case "system":
                addSystemMessage(message.content);
                break;
            default:
                // 作为普通文本消息处理
                addSystemMessage(typeof message === 'string' ? message : JSON.stringify(message));
        }

        // 在处理完所有消息类型后，统一进行代码高亮
        setTimeout(hljs.highlightAll, 0);

    } catch (e) {
        // 不是 JSON，作为普通文本处理
        addSystemMessage(data);
    }
}






function handleContentMessage(message) {
    // 隐藏欢迎屏幕
    document.querySelector('.welcome-screen').style.display = 'none';

    const chatMessages = document.getElementById('chat-messages');
    let aiMessage = null;
    let bubble = null;

    if (!currentAIMessageId) {
        // --- 开始一个新的 AI 消息 ---
        currentAIMessageId = "ai-" + Date.now();
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message message-ai';
        messageDiv.setAttribute('id', currentAIMessageId);

        messageDiv.innerHTML = `
            <div class="message-avatar">
                <i class="fas fa-robot"></i>
            </div>
            <div class="message-content">
                <div class="message-header">
                    <div class="message-sender">MCP AI</div>
                    <div class="message-time">${formatTime(new Date())}</div>
                </div>
                <div class="message-bubble ai"></div>
            </div>
        `;
        chatMessages.appendChild(messageDiv);
        aiMessage = messageDiv;
        bubble = aiMessage.querySelector('.message-bubble.ai');
        bubble.dataset.rawMarkdown = message.content; // 初始化

    } else {
        // --- 追加到现有的 AI 消息 ---
        aiMessage = document.getElementById(currentAIMessageId);
        if (aiMessage) {
            bubble = aiMessage.querySelector('.message-bubble.ai');
            bubble.dataset.rawMarkdown = (bubble.dataset.rawMarkdown || '') + message.content; // 累积
        } else {
            console.error("无法找到 AI 消息元素:", currentAIMessageId);
            currentAIMessageId = null;
            return;
        }
    }

    // --- 更新显示 ---
    if (bubble && bubble.dataset.rawMarkdown !== undefined) {
        const fullMarkdownContent = bubble.dataset.rawMarkdown;
        const htmlContent = marked.parse(fullMarkdownContent, { gfm: true, breaks: true });
        bubble.innerHTML = htmlContent;

        // --- LaTeX Rendering (KaTeX) ---
        // Ensure KaTeX's renderMathInElement function is available
        if (typeof renderMathInElement === 'function') {
            renderMathInElement(bubble, {
                // customised options
                // See https://katex.org/docs/options.html
                delimiters: [
                    {left: '$$', right: '$$', display: true}, // Block math
                    {left: '\\[', right: '\\]', display: true}, // Block math
                    {left: '$', right: '$', display: false},   // Inline math
                    {left: '\\(', right: '\\)', display: false}  // Inline math
                ],
                // For example, to display an error message in place of a malformed formula:
                throwOnError: false,
                // You can customize error color or behavior with errorColor or a custom macro
                // errorColor: '#cc0000',
            });
        } else {
            console.warn("KaTeX auto-render not available. LaTeX will not be rendered.");
        }

        // --- 代码块增强 (语言显示 + 复制按钮) ---
        enhanceCodeBlocks(bubble);

        // --- 代码高亮 (延迟执行) ---
        setTimeout(() => {
             const codeBlocksToHighlight = bubble.querySelectorAll('pre code:not(.hljs)');
             codeBlocksToHighlight.forEach((block) => {
                 hljs.highlightElement(block);
             });
        }, 0);
    }

    scrollToBottom();
}


// --- 新增：代码块增强函数 ---
function enhanceCodeBlocks(containerElement) {
    const preElements = containerElement.querySelectorAll('pre');
    preElements.forEach(pre => {
        const code = pre.querySelector('code');
        if (!code) return; // Skip if no <code> inside <pre>

        // --- 1. Extract Language ---
        let language = 'plaintext'; // Default
        // Check for class="language-xyz" added by marked.js
        const languageClass = Array.from(code.classList).find(cls => cls.startsWith('language-'));
        if (languageClass) {
            language = languageClass.replace('language-', '');
        } else if (code.className) {
            // Sometimes the class might just be the language name directly (less common with marked)
             language = code.className;
        }

        // Prevent adding duplicate controls if this runs multiple times quickly (though full innerHTML replace usually prevents this)
        if (pre.querySelector('.code-controls-wrapper')) {
             return;
        }

        // --- 2. Create Wrapper for Controls ---
        const controlsWrapper = document.createElement('div');
        controlsWrapper.className = 'code-controls-wrapper'; // Use a wrapper for positioning if needed, or style elements directly
        controlsWrapper.style.position = 'absolute'; // Style directly here or use CSS class
        controlsWrapper.style.top = '5px';
        controlsWrapper.style.left = '10px';
        controlsWrapper.style.right = '10px';
        controlsWrapper.style.display = 'flex';
        controlsWrapper.style.justifyContent = 'space-between';
        controlsWrapper.style.alignItems = 'center';
        controlsWrapper.style.height = '1.8em'; // Ensure space is consistent

        // --- 3. Create and Add Language Display ---
        const langDisplay = document.createElement('span');
        langDisplay.className = 'code-language-display';
        langDisplay.textContent = language;
        controlsWrapper.appendChild(langDisplay); // Add to wrapper

        // --- 4. Create and Add Copy Button ---
        const copyButton = document.createElement('button');
        copyButton.className = 'copy-code-button';
        copyButton.innerHTML = '<i class="fas fa-copy"></i> Copy'; // Requires Font Awesome
        copyButton.addEventListener('click', () => {
            navigator.clipboard.writeText(code.textContent)
                .then(() => {
                    copyButton.innerHTML = '<i class="fas fa-check"></i> Copied!';
                    copyButton.classList.add('copied');
                    setTimeout(() => {
                        copyButton.innerHTML = '<i class="fas fa-copy"></i> Copy';
                        copyButton.classList.remove('copied');
                    }, 2000); // Reset after 2 seconds
                })
                .catch(err => {
                    console.error('Failed to copy code:', err);
                    copyButton.textContent = 'Error';
                     setTimeout(() => {
                        copyButton.innerHTML = '<i class="fas fa-copy"></i> Copy';
                    }, 2000);
                });
        });
        controlsWrapper.appendChild(copyButton); // Add to wrapper

        // --- 5. Add Controls to the <pre> Element ---
        // Insert the wrapper at the beginning of the <pre> element
        pre.insertBefore(controlsWrapper, pre.firstChild);
    });
}




// 注意：在 `sendMessage` 和 `sendCommand` 函数中，确保在发送新消息或命令时，
// 将 currentAIMessageId 重置为 null，这部分代码已经是正确的：
// function sendMessage() {
//     ...
//     // 重置当前 AI 消息跟踪
//     currentAIMessageId = null; 
//     ...
// }
// function sendCommand(command) {
//     ...
//     // 重置当前 AI 消息跟踪
//     currentAIMessageId = null;
//     ...
// }
// 处理推理消息
function handleReasoningMessage(message) {
    if (typingIndicator) {
        removeTypingIndicator();
    }

    if (!showReasoning) {
        return;
    }

    const chatMessages = document.getElementById('chat-messages');
    if (!chatMessages) {
        console.error("Chat messages container not found!");
        return;
    }

    // 确定当前推理上下文的ID。这有助于在用户发起全新查询时重置计数器。
    // 如果 currentAIMessageId 存在且代表当前AI响应的唯一ID，优先使用它。
    // 否则，回退到 currentSessionId。
    // 这种上下文ID用于判断是否开启了一个全新的用户交互，从而决定是否重置思考步骤计数器。
    const contextId = currentAIMessageId || currentSessionId || `fallback-${Date.now()}`;

    // 如果上下文ID改变了（例如，用户发起了新的问题，导致 currentAIMessageId 更新），
    // 或者这是该上下文的第一个思考步骤，则重置计数器和当前消息引用。
    if (lastContextId !== contextId) {
        reasoningStepCounter = 0;
        currentReasoningMessageDiv = null; // 清除对上一个交互的思考气泡的引用
        currentReasoningBubble = null;
        lastContextId = contextId;
    }

    // 如果消息指示这是一个新的思考步骤，或者当前没有活动的思考气泡，
    // 则创建一个新的思考消息容器。
    if (message.newStep || !currentReasoningMessageDiv) {
        reasoningStepCounter++; // 增加步骤计数

        // 为新的思考消息容器创建唯一ID
        const thinkingStepId = `thinking-${contextId}-step-${reasoningStepCounter}`;

        const messageDiv = document.createElement('div');
        messageDiv.className = 'message message-reasoning';
        messageDiv.setAttribute('id', thinkingStepId);
        messageDiv.style.display = 'flex';

        messageDiv.innerHTML = `
            <div class="message-avatar reasoning">
                <i class="fas fa-brain"></i>
            </div>
            <div class="message-content">
                <div class="message-header">
                    <div class="message-sender">思考过程 #${reasoningStepCounter}</div>
                    <div class="message-time">${formatTime(new Date())}</div>
                </div>
                <div class="message-bubble reasoning"></div>
            </div>
        `;

        chatMessages.appendChild(messageDiv);
        currentReasoningMessageDiv = messageDiv; // 更新当前活动的思考消息容器
        currentReasoningBubble = messageDiv.querySelector('.message-bubble.reasoning'); // 更新当前活动的气泡
    }

    // 向当前活动的气泡追加内容
    if (currentReasoningBubble) {
        const trimmed = message.content.trim();
        // 对于流式输出，如果内容已经是空的，则不添加换行符
        // 仅当气泡内已有内容且新内容以标点结尾时，考虑添加换行
        if (currentReasoningBubble.innerHTML !== "" && /[。！？.!?]$/.test(trimmed)) {
            currentReasoningBubble.innerHTML += trimmed + "<br>";
        } else {
            currentReasoningBubble.innerHTML += trimmed;
        }
    } else {
        // 理论上不应该执行到这里，因为如果 currentReasoningBubble 为 null，
        // 前面的 if (message.newStep || !currentReasoningMessageDiv) 应该已经创建了它。
        // 但作为健壮性考虑，可以记录一个错误。
        console.error("Error: currentReasoningBubble is null. Cannot append message content.");
        // 可以考虑在这里强制创建一个新的思考气泡作为应急措施
        // return handleReasoningMessage({ ...message, newStep: true }); // 强制作为新步骤处理
        return;
    }

    scrollToBottom();
}

/**
 * 当AI完成所有思考并给出最终答复后，或者用户发起新请求时，
 * 调用此函数来“结束”当前的思考序列，以便下一次AI思考时能正确创建新的气泡组。
 */
function finalizeCurrentReasoningSequence() {
    currentReasoningMessageDiv = null;
    currentReasoningBubble = null;
    // reasoningStepCounter 和 lastContextId 会在下一次 handleReasoningMessage
    // 基于新的 contextId 自然重置或更新。
    // 你也可以在这里显式重置 lastContextId = null; 如果需要的话。
}
// 处理工具结果消息
function handleToolResultMessage(message) {
    // 移除打字指示器（如果存在）
    if (typingIndicator) {
        removeTypingIndicator();
    }
    
    const chatMessages = document.getElementById('chat-messages');
    const toolId = "tool-" + Date.now();
    
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message message-tool';
    messageDiv.setAttribute('id', toolId);
    
    // 格式化工具参数为JSON字符串
    let formattedArgs = '';
    try {
        if (typeof message.tool_args === 'object') {
            formattedArgs = JSON.stringify(message.tool_args, null, 2);
        } else {
            formattedArgs = String(message.tool_args);
        }
    } catch (e) {
        formattedArgs = String(message.tool_args);
    }
    
    messageDiv.innerHTML = `
        <div class="message-avatar tool">
            <i class="fas fa-tools"></i>
        </div>
        <div class="message-content">
            <div class="message-header">
                <div class="message-sender">${message.tool_name}</div>
                <div class="message-time">${formatTime(new Date())}</div>
            </div>
            <div class="message-bubble tool">参数: ${formattedArgs}
            
结果: ${message.tool_result}</div>
        </div>
    `;
    
    chatMessages.appendChild(messageDiv);
    
    // 显示打字指示器，等待预期响应
    showTypingIndicator();
    
    scrollToBottom();
}

// 添加用户消息
function addUserMessage(text) {
    const chatMessages = document.getElementById('chat-messages');
    
    // 隐藏欢迎屏幕
    document.querySelector('.welcome-screen').style.display = 'none';
    
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message message-user';
    
    messageDiv.innerHTML = `
        <div class="message-avatar user">
            <i class="fas fa-user"></i>
        </div>
        <div class="message-content">
            <div class="message-header">
                <div class="message-sender">用户</div>
                <div class="message-time">${formatTime(new Date())}</div>
            </div>
            <div class="message-bubble user">${escapeHtml(text)}</div>
        </div>
    `;
    
    chatMessages.appendChild(messageDiv);
    
    scrollToBottom();
}

// 添加系统消息 (支持Markdown格式和代码高亮)
function addSystemMessage(text) {
    const chatMessages = document.getElementById('chat-messages');
    
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message message-system';
    
    // 创建消息结构
    messageDiv.innerHTML = `
        <div class="message-avatar system">
            <i class="fas fa-info-circle"></i>
        </div>
        <div class="message-content">
            <div class="message-header">
                <div class="message-sender">系统</div>
                <div class="message-time">${formatTime(new Date())}</div>
            </div>
            <div class="message-bubble system"></div>
        </div>
    `;
    
    chatMessages.appendChild(messageDiv);
    
    // 获取气泡元素
    const bubble = messageDiv.querySelector('.message-bubble.system');
    
    // 存储原始 Markdown
    bubble.dataset.rawMarkdown = text;
    
    // 解析 Markdown 内容
    const htmlContent = marked.parse(text);
    bubble.innerHTML = htmlContent;
    
    // 延迟执行代码高亮
    setTimeout(() => {
        // 查找当前系统消息气泡内的所有 <pre><code> 块并高亮
        const codeBlocks = bubble.querySelectorAll('pre code');
        codeBlocks.forEach((block) => {
            hljs.highlightElement(block);
        });
    }, 0);
    
    scrollToBottom();
}
// 显示打字指示器
function showTypingIndicator() {
    // 仅在不存在时创建
    if (!typingIndicator) {
        const chatMessages = document.getElementById('chat-messages');
        
        typingIndicator = document.createElement('div');
        typingIndicator.className = 'message message-typing';
        
        typingIndicator.innerHTML = `
            <div class="message-avatar">
                <i class="fas fa-robot"></i>
            </div>
            <div class="message-content">
                <div class="typing-indicator">
                    <span class="typing-dot"></span>
                    <span class="typing-dot"></span>
                    <span class="typing-dot"></span>
                </div>
            </div>
        `;
        
        chatMessages.appendChild(typingIndicator);
        scrollToBottom();
    }
}

// 移除打字指示器
function removeTypingIndicator() {
    if (typingIndicator && typingIndicator.parentNode) {
        typingIndicator.parentNode.removeChild(typingIndicator);
        typingIndicator = null;
    }
}

// 发送消息
function sendMessage() {
    if (!isConnected) {
        addSystemMessage("未连接到服务器。正在尝试重新连接...");
        connectWebSocket();
        return;
    }
    
    const inputElement = document.getElementById('user-input');
    const message = inputElement.value.trim();
    
    if (message === '') return;
    
    // 重置当前 AI 消息跟踪
    currentAIMessageId = null;

    if (message === '/quit'){

        userRequestedDisconnect = true;
        console.log("用户输入/quit,WebSocket 连接已关闭");
        

    }
        

    // 创建新的会话ID
    conversationCounter++;
    currentSessionId = "session-" + conversationCounter;
    
    // 将用户消息添加到聊天
    addUserMessage(message);
    
    // 清空输入框
    inputElement.value = '';
    inputElement.style.height = 'auto';
    
    // 禁用发送按钮
    document.getElementById('send-button').disabled = true;
    
    // 显示打字指示器
    showTypingIndicator();
    isProcessing = true;
    
    // 发送消息
    socket.send(message);
}

// 发送命令
function sendCommand(command) {
    if (!isConnected) {
        addSystemMessage("未连接到服务器。正在尝试重新连接...");
        connectWebSocket();
        return;
    }
    
    // 重置当前 AI 消息跟踪
    currentAIMessageId = null;
    
    // 将命令添加到聊天
    addUserMessage(`/${command}`);
    
    // 显示打字指示器
    showTypingIndicator();
    isProcessing = true;
    
    // 发送命令
    socket.send(command);
}

// 填充示例消息
function fillExample(text) {
    const inputElement = document.getElementById('user-input');
    inputElement.value = text;
    inputElement.dispatchEvent(new Event('input'));
    inputElement.focus();
}

// 滚动到底部
function scrollToBottom() {
    const chatContainer = document.getElementById('chat-container');
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

// 格式化时间
function formatTime(date) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// HTML转义，防止XSS
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

