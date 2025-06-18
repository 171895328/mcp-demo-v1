import json
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
import requests
from datetime import datetime
from transformers import AutoTokenizer
import os



"""
load_dotenv('../SFmodel.env')

model_contextWindow = int(os.getenv('MODEL_API_OPTION_CONTEXTWINDOWS'))
# 设置令牌限制常量
print("当前LLM窗口大小设置为:",model_contextWindow)
"""


# 设置令牌限制
MAX_TOKENS = 128000
MIN_TOKENS_RESERVE = 500

class TokenCounter:
    """适用于 Qwen 模型的令牌计数器"""
    def __init__(self, model_name="Qwen/Qwen-7B-Chat"):
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
        except Exception as e:
            print(f"初始化 Qwen tokenizer 失败: {e}")
            self.tokenizer = None

    def count_message_tokens(self, message: Dict[str, Any]) -> int:
        """计算单条消息的 token 数"""
        if not self.tokenizer:
            return len(str(message)) // 4  # 退化为估算

        role = message.get("role", "")
        content = message.get("content", "")
        text = f"<|im_start|>{role}\n{content}<|im_end|>\n"
        return len(self.tokenizer.encode(text))

    def count_total_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """计算整个上下文的 token 总数"""
        return sum(self.count_message_tokens(msg) for msg in messages)

class ConversationManager:
    """对话管理器，负责维护消息历史"""
    def __init__(self, model_api_url: str, model_name: str, token_counter: TokenCounter):
        self.messages: List[Dict[str, Any]] = []
        self.token_counter = token_counter
        self.model_api_url = model_api_url
        self.model_name = model_name
        self.system_summary = None
        self.tool_context = None  # 存储工具上下文摘要
        self.key_messages = []  # 存储被标记为重要的消息
        self.compression_stages = {
            "stage1": 0.8,  # 第一阶段，保留80%的令牌
            "stage2": 0.6,  # 第二阶段，保留60%的令牌
            "stage3": 0.4   # 第三阶段，保留40%的令牌
        }
    
    def add_message(self, message: Dict[str, Any], is_key_message: bool = False) -> None:
        """
        添加消息到历史
        
        Args:
            message: 要添加的消息
            is_key_message: 是否为关键消息（关键消息在压缩时会被尽量保留）
        """
        # 添加时间戳和重要性标记
        message["timestamp"] = datetime.now().isoformat()
        message["is_key"] = is_key_message
        
        if is_key_message:
            self.key_messages.append(len(self.messages))  # 记录关键消息的索引
            
        self.messages.append(message)
    
    def mark_as_key_message(self, message_index: int) -> None:
        """将指定索引的消息标记为关键消息"""
        if 0 <= message_index < len(self.messages):
            self.messages[message_index]["is_key"] = True
            if message_index not in self.key_messages:
                self.key_messages.append(message_index)
    
    def get_current_messages(self) -> List[Dict[str, Any]]:
        """获取当前的消息历史，包括摘要和工具上下文"""
        result = []
        
        # 添加对话摘要（如果有）
        if self.system_summary:
            result.append(self.system_summary)
            
        # 添加工具上下文（如果有）
        if self.tool_context:
            result.append(self.tool_context)
            
        # 添加常规消息，但移除内部用的元数据字段
        for msg in self.messages:
            clean_msg = {k: v for k, v in msg.items() 
                        if k not in ["timestamp", "is_key", "importance_score"]}
            result.append(clean_msg)
        
        return result
    
    def get_last_user_question(self) -> Optional[str]:
        """获取最后一个用户问题，用于生成针对性摘要"""
        for msg in reversed(self.messages):
            if msg.get("role") == "user":
                return msg.get("content", "")
        return None
        
    def update_tool_context(self, tools_info: str) -> None:
        """更新工具上下文信息"""
        self.tool_context = {
            "role": "system",
            "content": f"""以下是你可以使用的工具信息：

{tools_info}

请根据用户需求选择合适的工具。"""
        }
    
    async def optimize_history(self) -> None:
        """智能优化历史记录以保持在令牌限制内"""
        # 获取当前令牌数
        current_messages = self.get_current_messages()
        total_tokens = self.token_counter.count_total_tokens(current_messages)
        
        # 如果令牌数低于限制，不需要优化
        if total_tokens <= MAX_TOKENS - MIN_TOKENS_RESERVE:
            return
            
        # 多阶段压缩策略
        compression_needed = total_tokens - (MAX_TOKENS - MIN_TOKENS_RESERVE)
        
        # 1. 尝试智能过滤非关键消息
        if compression_needed > 0:
            self._filter_non_essential_messages()
            # 重新计算令牌数
            current_messages = self.get_current_messages()
            total_tokens = self.token_counter.count_total_tokens(current_messages)
            compression_needed = total_tokens - (MAX_TOKENS - MIN_TOKENS_RESERVE)
        
        # 2. 如果仍然需要压缩，对对话分块并摘要化较早的部分
        if compression_needed > 0:
            await self._summarize_conversation_segments()
            # 重新计算令牌数
            current_messages = self.get_current_messages()
            total_tokens = self.token_counter.count_total_tokens(current_messages)
            compression_needed = total_tokens - (MAX_TOKENS - MIN_TOKENS_RESERVE)
            
        # 3. 如果仍然超过限制，保留最近的重要消息和用户问题
        if compression_needed > 0:
            self._preserve_critical_context()
    
    def _filter_non_essential_messages(self) -> None:
        """过滤掉非必要的中间消息，保留关键节点"""
        if len(self.messages) <= 4:  # 如果消息太少，不进行过滤
            return
            
        # 计算每条消息的重要性分数
        scored_messages = []
        for i, msg in enumerate(self.messages):
            score = self._calculate_message_importance(msg, i)
            scored_messages.append((i, score))
            
        # 按重要性排序
        scored_messages.sort(key=lambda x: x[1], reverse=True)
        
        # 确定要保留的消息数量（基于当前阶段）
        stage = "stage1"  # 默认第一阶段
        keep_ratio = self.compression_stages[stage]
        keep_count = max(4, int(len(self.messages) * keep_ratio))
        
        # 获取要保留的消息索引（按原始顺序）
        indices_to_keep = [idx for idx, _ in sorted(scored_messages[:keep_count])]
        
        # 保留选定的消息和最新的几条消息
        recent_count = min(4, len(self.messages))
        recent_indices = list(range(len(self.messages) - recent_count, len(self.messages)))
        
        # 合并保留索引（确保包含最近消息）
        all_indices = sorted(set(indices_to_keep + recent_indices))
        
        # 重建消息列表
        self.messages = [self.messages[i] for i in all_indices]
        
        # 更新key_messages索引
        new_key_messages = []
        for i, idx in enumerate(all_indices):
            if idx in self.key_messages:
                new_key_messages.append(i)
        self.key_messages = new_key_messages
    
    def _calculate_message_importance(self, message: Dict[str, Any], index: int) -> float:
        """计算消息的重要性分数"""
        score = 0.0
        
        # 关键消息得到最高分
        if message.get("is_key", False):
            score += 100.0
            
        # 根据消息类型评分
        role = message.get("role", "")
        if role == "user":
            score += 10.0  # 用户问题通常更重要
        elif role == "assistant":
            score += 5.0   # 助手回答次之
        elif role == "system":
            score += 15.0  # 系统消息非常重要
            
        # 最近的消息更重要
        recency_score = index / len(self.messages) * 10
        score += recency_score
        
        # 检查内容长度和信息密度
        content = message.get("content", "")
        if content:
            # 长度因素
            length_score = min(5.0, len(content) / 500)
            score += length_score
            
            # 判断是否包含工具调用或关键结果
            if "tool" in content.lower() or "结果" in content or "数据" in content:
                score += 8.0
                
            # 判断是否包含代码块
            if "```" in content:
                score += 5.0
                
        return score
            
    async def _summarize_conversation_segments(self) -> None:
        """将对话分段并对较早的部分进行摘要"""
        if len(self.messages) <= 6:  # 至少需要足够多的消息才值得摘要
            return
            
        # 确定分割点，保留最新的4-6轮对话
        recent_turns = min(6, max(len(self.messages) // 3, 4))
        split_index = len(self.messages) - recent_turns
        
        # 分离较早和最近的消息
        earlier_messages = self.messages[:split_index]
        recent_messages = self.messages[split_index:]
        
        if not earlier_messages:
            return
            
        # 获取最新的用户问题，用于上下文相关摘要
        last_question = self.get_last_user_question()
        
        # 生成包含了关键信息的摘要
        summary = await self._generate_focused_summary(earlier_messages, last_question)
        
        # 更新系统摘要
        self.system_summary = {
            "role": "system",
            "content": f"""以下是之前对话的详细摘要：

            {summary}

            请基于此摘要继续对话，保持连贯性。如有必要，可以参考摘要中的关键信息。"""
                    }
        
        # 更新消息列表
        self.messages = recent_messages
        
        # 更新key_messages索引
        self.key_messages = [i for i in self.key_messages if i >= split_index]
        self.key_messages = [i - split_index for i in self.key_messages]
    
    async def _generate_focused_summary(self, 
                                     messages: List[Dict[str, Any]], 
                                     last_question: Optional[str] = None) -> str:
        """生成针对当前上下文的详细摘要"""
        try:
            # 提取关键信息，如工具调用、代码片段和重要结果
            key_info = self._extract_key_information(messages)
            
            # 生成指导提示，引导模型保留更多细节
            guidance = f"""请详细总结以下对话，必须满足这些要求：
                        1. 保留所有重要上下文和用户意图
                        2. 详细保留所有工具调用及其结果
                        3. 完整保留代码片段和技术细节
                        4. 保留数据分析结果和关键数字
                        5. 摘要应该详尽而不是笼统，以便未来对话可以无缝继续
                        6. 对话摘要应该有足够的细节，使得模型可以基于它回答具体问题

                        特别关注这些关键信息：
                        {key_info}
                        """
            
            # 如果有最新的用户问题，引导摘要与其相关
            if last_question:
                guidance += f"\n\n最新用户问题是：\"{last_question}\"\n请确保摘要保留与这个问题相关的所有背景信息。"
            
            # 准备摘要请求
            summary_request = [
                {"role": "system", "content": guidance}
            ] + messages
            
            # 调用模型生成摘要
            data = {
                "model": self.model_name,
                "messages": summary_request,
                "stream": False
            }
            
            headers = {'Content-type': 'application/json'}
            response = requests.post(
                self.model_api_url,
                data=json.dumps(data),
                headers=headers
            )
            
            if response.status_code == 200:
                summary = response.json().get("message", {}).get("content", "")
                return summary
            
            return "无法生成有效摘要，但对话包含工具调用和重要信息。" 
        except Exception as e:
            print(f"生成摘要失败: {str(e)}")
            return "生成摘要过程中出错，但请记住对话中包含了工具调用和重要结果。"
    
    def _extract_key_information(self, messages: List[Dict[str, Any]]) -> str:
        """从消息中提取关键信息片段"""
        key_info = []
        
        for msg in messages:
            content = msg.get("content", "")
            role = msg.get("role", "")
            
            # 提取工具调用
            if "tool" in content.lower() or "函数" in content:
                # 尝试提取工具调用片段
                start_idx = max(0, content.lower().find("tool"))
                end_idx = min(len(content), start_idx + 300)
                tool_info = content[start_idx:end_idx].strip()
                key_info.append(f"工具调用: {tool_info}...")
                
            # 提取代码片段
            if "```" in content:
                code_blocks = []
                lines = content.split("\n")
                in_code_block = False
                current_block = []
                
                for line in lines:
                    if line.startswith("```"):
                        if in_code_block:
                            # 结束代码块
                            code_blocks.append("\n".join(current_block))
                            current_block = []
                        in_code_block = not in_code_block
                    elif in_code_block:
                        current_block.append(line)
                
                for i, block in enumerate(code_blocks):
                    key_info.append(f"代码片段{i+1}: {block[:100]}...")
                    
            # 提取可能的结果或数据
            if role == "assistant" and ("结果" in content or "数据" in content):
                # 提取结果相关的段落
                paragraphs = content.split("\n\n")
                for para in paragraphs:
                    if "结果" in para or "数据" in para:
                        key_info.append(f"结果信息: {para[:200]}...")
                        break
        
        # 拼接提取的关键信息
        if key_info:
            return "\n\n".join(key_info)
        else:
            return "未发现明显的关键信息，请保留对话的主要内容和用户问题。"
            
    def _preserve_critical_context(self) -> None:
        """在令牌严重超限的情况下，只保留最关键的上下文"""
        # 保留系统消息、最新的用户问题和答复，以及标记为关键的消息
        
        # 1. 找出所有系统消息
        system_indices = [i for i, msg in enumerate(self.messages) 
                          if msg.get("role") == "system"]
                          
        # 2. 找出最新的2轮对话
        recent_indices = list(range(max(0, len(self.messages) - 4), len(self.messages)))
        
        # 3. 合并所有需要保留的索引
        keep_indices = sorted(set(system_indices + recent_indices + self.key_messages))
        
        # 如果需要保留的消息仍然太多，只保留绝对必要的部分
        if len(keep_indices) > 6:
            # 确保保留最新的用户问题和回答
            last_user_idx = None
            for i in reversed(range(len(self.messages))):
                if self.messages[i].get("role") == "user":
                    last_user_idx = i
                    break
                    
            # 如果找到了最新用户问题，确保保留它和它之后的回答
            if last_user_idx is not None:
                must_keep = [last_user_idx]
                if last_user_idx < len(self.messages) - 1:
                    must_keep.append(last_user_idx + 1)
                    
                # 合并必须保留的关键消息
                must_keep_key = [i for i in self.key_messages if i in keep_indices][:2]
                
                # 最终保留的消息索引
                keep_indices = sorted(set(must_keep + must_keep_key + system_indices))
        
        # 更新消息列表
        self.messages = [self.messages[i] for i in keep_indices]
        
        # 更新key_messages索引
        new_key_messages = []
        for i, old_idx in enumerate(keep_indices):
            if old_idx in self.key_messages:
                new_key_messages.append(i)
        self.key_messages = new_key_messages
        
        # 添加一个警告消息，告知用户上下文已大幅压缩
        self.system_summary = {
            "role": "system",
            "content": "注意：由于对话长度超过限制，系统已保留最关键的上下文信息。如果需要参考之前的内容，请明确提醒助手。"
        }
    
    def diminishMessages(self):
        """清空历史消息"""
        self.messages = []
        self.key_messages = []
        self.system_summary = None
        print(f"已清空历史消息")
        
    def diminishRoleMessages(self,role:str):
        
       self.messages = [msg for msg in self.messages if msg["role"] != role]
            
    def removeMessageByContent(self, target_content: str):
        self.messages = [
            msg for msg in self.messages
            if msg["content"].strip() != target_content.strip()
        ]      
        
    def mark_current_exchange_as_key(self):
        """将当前最新的问答交互标记为关键信息"""
        if len(self.messages) >= 2:
            # 标记最后一个用户问题
            for i in range(len(self.messages)-1, -1, -1):
                if self.messages[i].get("role") == "user":
                    self.mark_as_key_message(i)
                    # 同时标记对应的回答（如果存在）
                    if i+1 < len(self.messages) and self.messages[i+1].get("role") == "assistant":
                        self.mark_as_key_message(i+1)
                    break
                
                    
    def diminishByRoleAndKey(self,  role: str = "system", keyword: str = "推荐的工作流程"):
        # 删除已有提示消息（避免重复）
        self.messages = [
            msg for msg in self.messages
            if not (msg["role"] == role and keyword in msg["content"])
        ]

