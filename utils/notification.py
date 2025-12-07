"""
通知管理模块
支持邮件和企业微信通知
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import List, Dict, Optional
import json
import urllib.request
import urllib.error

from .logger import get_logger

logger = get_logger()


class NotificationManager:
    """
    通知管理器
    支持邮件和企业微信通知
    """

    def __init__(self, config: Dict = None):
        """
        初始化通知管理器

        Args:
            config: 通知配置，包含email和wechat配置
        """
        self.config = config or {}
        self.enabled = self.config.get('enabled', False)
        self.email_config = self.config.get('email', {})
        self.wechat_config = self.config.get('wechat', {})

    def send_notification(
        self,
        title: str,
        content: str,
        level: str = "info",
        channels: List[str] = None
    ):
        """
        发送通知

        Args:
            title: 通知标题
            content: 通知内容
            level: 通知级别 (info, warning, error)
            channels: 发送渠道 ['email', 'wechat']，默认全部
        """
        if not self.enabled:
            logger.debug(f"通知未启用，跳过: {title}")
            return

        channels = channels or ['email', 'wechat']

        if 'email' in channels and self.email_config:
            try:
                self._send_email(title, content, level)
            except Exception as e:
                logger.error(f"邮件发送失败: {e}")

        if 'wechat' in channels and self.wechat_config.get('enabled'):
            try:
                self._send_wechat(title, content, level)
            except Exception as e:
                logger.error(f"企业微信发送失败: {e}")

    def _send_email(self, title: str, content: str, level: str):
        """发送邮件通知"""
        smtp_server = self.email_config.get('smtp_server')
        smtp_port = self.email_config.get('smtp_port', 465)
        sender = self.email_config.get('sender')
        password = self.email_config.get('password')
        receivers = self.email_config.get('receivers', [])

        if not all([smtp_server, sender, password, receivers]):
            logger.warning("邮件配置不完整，跳过发送")
            return

        # 构建邮件
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"[量化交易-{level.upper()}] {title}"
        msg['From'] = sender
        msg['To'] = ', '.join(receivers)

        # 构建HTML内容
        level_colors = {
            'info': '#17a2b8',
            'warning': '#ffc107',
            'error': '#dc3545'
        }
        color = level_colors.get(level, '#17a2b8')

        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <div style="border-left: 4px solid {color}; padding-left: 15px;">
                <h2 style="color: {color}; margin-top: 0;">{title}</h2>
                <div style="color: #333; white-space: pre-wrap;">{content}</div>
                <p style="color: #999; font-size: 12px; margin-top: 20px;">
                    发送时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                </p>
            </div>
        </body>
        </html>
        """

        msg.attach(MIMEText(content, 'plain', 'utf-8'))
        msg.attach(MIMEText(html_content, 'html', 'utf-8'))

        # 发送邮件
        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(sender, password)
            server.sendmail(sender, receivers, msg.as_string())

        logger.info(f"邮件发送成功: {title}")

    def _send_wechat(self, title: str, content: str, level: str):
        """发送企业微信通知"""
        corp_id = self.wechat_config.get('corp_id')
        agent_id = self.wechat_config.get('agent_id')
        secret = self.wechat_config.get('secret')

        if not all([corp_id, agent_id, secret]):
            logger.warning("企业微信配置不完整，跳过发送")
            return

        # 获取access_token
        token_url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={corp_id}&corpsecret={secret}"

        try:
            with urllib.request.urlopen(token_url) as response:
                token_data = json.loads(response.read().decode())
                access_token = token_data.get('access_token')
        except urllib.error.URLError as e:
            logger.error(f"获取企业微信token失败: {e}")
            return

        if not access_token:
            logger.error("获取企业微信access_token失败")
            return

        # 发送消息
        send_url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={access_token}"

        level_emojis = {
            'info': 'ℹ️',
            'warning': '⚠️',
            'error': '🚨'
        }
        emoji = level_emojis.get(level, 'ℹ️')

        message = {
            "touser": "@all",
            "msgtype": "text",
            "agentid": agent_id,
            "text": {
                "content": f"{emoji} {title}\n\n{content}\n\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            }
        }

        try:
            req = urllib.request.Request(
                send_url,
                data=json.dumps(message).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode())
                if result.get('errcode') == 0:
                    logger.info(f"企业微信发送成功: {title}")
                else:
                    logger.error(f"企业微信发送失败: {result}")
        except urllib.error.URLError as e:
            logger.error(f"企业微信发送失败: {e}")

    # ============ 便捷方法 ============

    def notify_trade(
        self,
        action: str,
        stock_code: str,
        stock_name: str,
        price: float,
        amount: int,
        strategy: str
    ):
        """交易通知"""
        action_text = "买入" if action == "buy" else "卖出"
        total = price * amount

        title = f"{action_text}成功 - {stock_name}({stock_code})"
        content = f"""
交易类型: {action_text}
股票代码: {stock_code}
股票名称: {stock_name}
成交价格: {price:.2f}
成交数量: {amount}
成交金额: {total:.2f}
交易策略: {strategy}
        """.strip()

        self.send_notification(title, content, level="info")

    def notify_signal(
        self,
        stock_code: str,
        stock_name: str,
        signal_type: str,
        strategy: str,
        reason: str
    ):
        """信号通知"""
        signal_text = "买入信号" if signal_type == "buy" else "卖出信号"

        title = f"{signal_text} - {stock_name}({stock_code})"
        content = f"""
信号类型: {signal_text}
股票代码: {stock_code}
股票名称: {stock_name}
触发策略: {strategy}
触发原因: {reason}
        """.strip()

        self.send_notification(title, content, level="info")

    def notify_risk_warning(
        self,
        event_type: str,
        details: str,
        action_taken: str = ""
    ):
        """风控预警通知"""
        title = f"风控预警 - {event_type}"
        content = f"""
预警类型: {event_type}
详细信息: {details}
采取措施: {action_taken or '无'}
        """.strip()

        self.send_notification(title, content, level="warning")

    def notify_error(self, error_type: str, error_msg: str):
        """错误通知"""
        title = f"系统错误 - {error_type}"
        content = f"""
错误类型: {error_type}
错误信息: {error_msg}
        """.strip()

        self.send_notification(title, content, level="error")

    def notify_daily_summary(
        self,
        total_assets: float,
        daily_profit: float,
        daily_profit_pct: float,
        positions: List[Dict],
        trades_count: int
    ):
        """每日总结通知"""
        profit_emoji = "📈" if daily_profit >= 0 else "📉"

        positions_text = ""
        for pos in positions[:5]:  # 最多显示5个持仓
            positions_text += f"  {pos['stock_name']}({pos['stock_code']}): {pos.get('profit_pct', 0):.2%}\n"

        if not positions_text:
            positions_text = "  无持仓\n"

        title = f"每日交易总结 {profit_emoji}"
        content = f"""
【账户概况】
总资产: {total_assets:,.2f}
今日盈亏: {daily_profit:,.2f} ({daily_profit_pct:.2%})
今日交易: {trades_count}笔

【持仓情况】
{positions_text}
        """.strip()

        level = "info" if daily_profit >= 0 else "warning"
        self.send_notification(title, content, level=level)
