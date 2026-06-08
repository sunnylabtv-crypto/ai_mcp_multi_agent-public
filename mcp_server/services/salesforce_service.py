# mcp_server/services/salesforce_service.py
"""
Salesforce API 서비스 (멀티유저 지원, JWT Bearer Flow)
"""
import os
import time
import re
import logging
import jwt
import requests
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ============================================================
# 단일 사용자 모드 (기존 호환)
# ============================================================

_salesforce_config = None
_access_token = None
_instance_url = None


def authenticate_salesforce(config: dict) -> bool:
    """Salesforce JWT Bearer Flow 인증 (단일 사용자)"""
    global _salesforce_config, _access_token, _instance_url
    
    _salesforce_config = config
    
    logger.info("Salesforce JWT 토큰 요청 중...")
    
    try:
        consumer_key = _salesforce_config.get('CONSUMER_KEY')
        username = _salesforce_config.get('USERNAME')
        login_url = _salesforce_config.get('LOGIN_URL')
        key_path = _salesforce_config.get('JWT_KEY_PATH')
        
        if not all([consumer_key, username, login_url, key_path]):
            logger.error("❌ Salesforce 설정이 완전하지 않습니다.")
            return False
        
        try:
            with open(key_path, "r", encoding="utf-8") as f:
                private_key = f.read().strip()
        except FileNotFoundError:
            logger.error(f"❌ 개인키 파일을 찾을 수 없습니다: {key_path}")
            return False
        
        now = int(time.time())
        payload = {
            "iss": consumer_key,
            "sub": username,
            "aud": login_url,
            "iat": now,
            "exp": now + 180
        }
        
        assertion = jwt.encode(payload, private_key, algorithm="RS256")
        if isinstance(assertion, bytes):
            assertion = assertion.decode("utf-8")
        
        token_url = f"{login_url}/services/oauth2/token"
        
        response = requests.post(
            token_url,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=20,
        )
        
        if response.status_code == 200:
            token_data = response.json()
            _access_token = token_data["access_token"]
            _instance_url = token_data["instance_url"]
            
            logger.info("✅ Salesforce JWT 토큰 획득 성공!")
            logger.info(f"   Instance URL: {_instance_url}")
            return True
        else:
            logger.error(f"❌ 토큰 요청 실패: {response.status_code}")
            logger.error(f"   응답: {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Salesforce 인증 실패: {e}", exc_info=True)
        return False


def get_service_status() -> Dict:
    """Salesforce 서비스 상태 (단일 사용자)"""
    global _salesforce_config, _access_token, _instance_url
    return {
        'configured': _salesforce_config is not None,
        'authenticated': _access_token is not None,
        'instance_url': _instance_url,
        'username': _salesforce_config.get('USERNAME') if _salesforce_config else None
    }


# ============================================================
# 멀티유저 모드
# ============================================================

_user_sf_sessions: Dict[str, dict] = {}


def authenticate_salesforce_for_user(user_id: str, config: dict) -> bool:
    """사용자별 Salesforce 인증"""
    global _user_sf_sessions
    
    logger.info(f"Salesforce 인증 시작 (사용자: {user_id})...")
    
    try:
        consumer_key = config.get('CONSUMER_KEY')
        username = config.get('USERNAME')
        login_url = config.get('LOGIN_URL')
        key_path = config.get('JWT_KEY_PATH')
        
        if not all([consumer_key, username, login_url, key_path]):
            logger.error(f"❌ Salesforce 설정이 완전하지 않습니다 (사용자: {user_id})")
            return False
        
        if not os.path.exists(key_path):
            logger.error(f"❌ JWT Key 파일 없음: {key_path}")
            return False
        
        with open(key_path, "r", encoding="utf-8") as f:
            private_key = f.read().strip()
        
        now = int(time.time())
        payload = {
            "iss": consumer_key,
            "sub": username,
            "aud": login_url,
            "iat": now,
            "exp": now + 180
        }
        
        assertion = jwt.encode(payload, private_key, algorithm="RS256")
        if isinstance(assertion, bytes):
            assertion = assertion.decode("utf-8")
        
        token_url = f"{login_url}/services/oauth2/token"
        
        response = requests.post(
            token_url,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=20,
        )
        
        if response.status_code == 200:
            token_data = response.json()
            
            _user_sf_sessions[user_id] = {
                'config': config,
                'access_token': token_data["access_token"],
                'instance_url': token_data["instance_url"]
            }
            
            logger.info(f"✅ Salesforce 인증 성공! 사용자: {user_id}")
            logger.info(f"   Instance URL: {token_data['instance_url']}")
            return True
        else:
            logger.error(f"❌ 토큰 요청 실패 (사용자: {user_id}): {response.status_code}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Salesforce 인증 실패 (사용자: {user_id}): {e}", exc_info=True)
        return False


def get_user_service_status(user_id: str) -> Dict:
    """사용자별 Salesforce 상태"""
    if user_id in _user_sf_sessions:
        session = _user_sf_sessions[user_id]
        return {
            'configured': True,
            'authenticated': True,
            'instance_url': session['instance_url'],
            'username': session['config'].get('USERNAME')
        }
    return {
        'configured': False,
        'authenticated': False,
        'instance_url': None,
        'username': None
    }


def _get_sf_session(user_id: str = None):
    """현재 컨텍스트의 Salesforce 세션 반환"""
    if user_id and user_id in _user_sf_sessions:
        session = _user_sf_sessions[user_id]
        return session['access_token'], session['instance_url']
    return _access_token, _instance_url


# ============================================================
# Salesforce 기능 함수들
# ============================================================

def create_lead(customer_info: Dict, user_id: str = None) -> Optional[str]:
    """Salesforce Lead 생성"""
    access_token, instance_url = _get_sf_session(user_id)
    
    if not access_token or not instance_url:
        logger.error("❌ Salesforce 인증이 필요합니다")
        return None
    
    try:
        name = customer_info.get('name', '')
        if name:
            name_parts = name.strip().split()
            if len(name_parts) >= 2:
                last_name = name_parts[0]
                first_name = ' '.join(name_parts[1:])
            else:
                last_name = name
                first_name = ''
        else:
            last_name = 'Unknown'
            first_name = ''
        
        email = customer_info.get('email', '')
        if email:
            email_match = re.search(r'<(.+?)>', email)
            if email_match:
                email = email_match.group(1)
            email = email.strip()
        
        lead_data = {
            "LastName": last_name,
            "FirstName": first_name,
            "Company": customer_info.get('company', 'Unknown'),
            "Title": customer_info.get('title', ''),
            "Phone": customer_info.get('phone', ''),
            "Email": email,
            "LeadSource": "Email Inquiry",
            "Status": "Open - Not Contacted",
            "Description": "자동 이메일 워크플로우를 통해 생성된 Lead"
        }
        
        lead_url = f"{instance_url}/services/data/v60.0/sobjects/Lead/"
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        response = requests.post(lead_url, headers=headers, json=lead_data, timeout=30)
        
        if response.status_code == 201:
            result = response.json()
            lead_id = result['id']
            logger.info(f"✅ Lead 생성 성공! ID: {lead_id}")
            return lead_id
        else:
            logger.error(f"❌ Lead 생성 실패: {response.status_code}")
            logger.error(f"   응답: {response.text}")
            return None
        
    except Exception as e:
        logger.error(f"❌ Lead 생성 중 오류: {e}", exc_info=True)
        return None


def verify_lead(lead_id: str, user_id: str = None) -> Optional[Dict]:
    """Lead 정보 확인"""
    access_token, instance_url = _get_sf_session(user_id)
    
    if not access_token or not instance_url:
        logger.error("❌ Salesforce 인증이 필요합니다")
        return None
    
    try:
        lead_url = f"{instance_url}/services/data/v60.0/sobjects/Lead/{lead_id}"
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        response = requests.get(lead_url, headers=headers, timeout=30)
        
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"❌ Lead 정보 확인 실패: {response.status_code}")
            return None
            
    except Exception as e:
        logger.error(f"❌ Lead 확인 중 오류: {e}", exc_info=True)
        return None


def get_lead_url(lead_id: str, user_id: str = None) -> Optional[str]:
    """Lead 웹 URL 생성"""
    _, instance_url = _get_sf_session(user_id)
    
    if not instance_url:
        return None
    
    return f"{instance_url}/lightning/r/Lead/{lead_id}/view"
