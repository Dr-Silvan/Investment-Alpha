# 투자 0.9.1-beta

## 0.9.1 변경 사항

- API 키 없이 바로 사용할 수 있도록 yfinance를 기본 시장 데이터 공급자로 복원
- 시장 데이터 설정에서 yfinance와 Alpaca historical SIP를 선택 가능
- 기존 Alpaca 발급 온보딩 대신 Swing·Day 탭과 주요 버튼을 설명하는 5페이지 앱 사용 설명서 추가
- 상단 설정 버튼 옆의 책 아이콘으로 사용 설명서를 언제든 다시 열 수 있음

Investment Beta가 **투자**로 이름과 아이콘을 새롭게 정리한 첫 설치형 베타 릴리스입니다.

## 주요 내용

- Swing과 Day 모드를 하나의 로컬 우선 워크스테이션으로 통합
- Trade Planner·Import Position 공통 전략 카탈로그 관리
- 전략 추가·숨김·복원 및 사용된 전략의 과거 통계 보존
- 포지션 lifecycle, 분할매수·분할매도, 손절 변경과 위험 추적
- 자산·입출금·실현손익 원장과 Analytics
- 섹터 대표주·SPY·QQQ 상대수익률
- 미국 주요 경제지표와 향후 7일 이벤트 레이더
- Exit Quality와 Chicken-out 가능성 복기
- 앱 시작 시 최근 완료된 미국장 종가 자동 갱신
- Alpaca historical SIP provider와 첫 실행 API 연결 튜토리얼
- Windows DPAPI 기반 API Key·Secret 암호화 저장
- 루프백·Host·Origin 검증과 브라우저 보안 헤더 적용
- 외부 경제 일정 문자열과 링크 출력 정제
- 개인 경로가 없는 재현 가능한 Windows 빌드 스크립트
- 깨끗한 Windows 가상머신의 빌드·설치·첫 실행·제거 후 데이터 보존 검증

## Windows 설치

`Tuja-Setup-0.9.1-beta.exe`를 내려받아 실행합니다. Windows SmartScreen은 코드 서명이 없는 개인 베타 앱에 경고를 표시할 수 있습니다.

- Python 런타임 포함
- 시작 메뉴와 선택형 바탕화면 바로가기
- 사용자 데이터 위치: `%LOCALAPPDATA%\투자\data`
- 기존 Desktop `Investment-beta` 데이터가 있으면 최초 실행 시 자동 이전

## 무결성

SHA-256은 GitHub Release의 자산 설명과 함께 제공됩니다.

## 주의

개인 기록·분석용 베타 소프트웨어이며 투자 자문이나 수익 보장을 제공하지 않습니다.

시장 데이터 제공자의 정책과 가용성에 따라 온라인 가격 조회가 제한되거나 변경될 수 있습니다. 네트워크 조회 결과는 주문 체결이나 실시간 시세로 사용하지 마십시오.
