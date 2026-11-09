# 조립PC 트렌드 모니터

거래처 유튜브 채널에 새 영상이 올라오면 6시간 안에 **자동으로 영상을 분석**(요약 · 언급 제품 · 제품별 평가/가격 · 영업 시사점)하고, **텔레그램으로 알림**을 보내며, **웹페이지**(PC·모바일)에서 피드와 제품 트렌드를 볼 수 있는 도구입니다.

```
GitHub Actions (6시간마다)
  ├─ 채널 RSS 확인 → 새 영상 발견
  ├─ Gemini API가 유튜브 영상을 직접 시청·분석 (무료 한도 내)
  ├─ data/ 폴더에 결과 저장
  └─ 텔레그램 알림
GitHub Pages → 웹페이지 (영상 피드 / 제품 트렌드 / 채널 관리)
```

비용: GitHub·텔레그램 무료, Gemini 무료 등급(하루 유튜브 영상 8시간 분량까지).

---

## 설치 (처음 한 번, 약 30분)

### 1. GitHub 가입 및 저장소 만들기
1. https://github.com/signup 에서 가입 (회사 메일 사용 가능)
2. 오른쪽 위 **+** → **New repository**
   - Repository name: `yt-trend-monitor`
   - **Public** 선택 (무료로 웹페이지를 띄우려면 공개 저장소여야 합니다 — 아래 '참고' 확인)
   - **Create repository**

### 2. 파일 올리기
1. 받은 zip 파일 압축을 풉니다.
2. 저장소 화면의 **uploading an existing file** 링크 클릭 → 폴더 안의 파일·폴더를 모두 끌어다 놓기 → **Commit changes**
3. `.github` 폴더는 숨김 폴더라 빠질 수 있습니다. 저장소에 `.github` 가 안 보이면:
   - **Add file → Create new file**
   - 파일 이름 칸에 `.github/workflows/monitor.yml` 입력
   - zip 안의 같은 파일 내용을 메모장으로 열어 복사·붙여넣기 → **Commit changes**
   - `.github/workflows/test-telegram.yml` 도 같은 방법으로 추가

### 3. Gemini API 키 받기
1. https://aistudio.google.com/apikey 접속 (구글 계정 로그인)
2. **API 키 만들기** → 키 복사 (`AIza…`)

### 4. 텔레그램 봇 만들기
1. 텔레그램에서 **@BotFather** 검색 → `/newbot` 입력
2. 봇 이름, 아이디(끝이 `bot`) 입력 → **토큰**(`123456:ABC…`)을 복사
3. 방금 만든 봇을 검색해 대화방을 열고 아무 메시지(예: `안녕`)를 보냅니다.
4. 브라우저에서 아래 주소를 엽니다 (`<토큰>` 자리에 복사한 토큰):
   `https://api.telegram.org/bot<토큰>/getUpdates`
5. 결과에서 `"chat":{"id":123456789` 의 숫자가 **Chat ID** 입니다.
   - 팀원과 함께 받으려면 텔레그램 그룹에 봇을 초대 → 그룹에서 메시지 하나 보내고 같은 방법으로 확인 (그룹 ID는 `-` 로 시작)
   - 여러 곳으로 보내려면 쉼표로 구분: `123456789,-100987654321`

### 5. 비밀값 등록
저장소 **Settings → Secrets and variables → Actions → New repository secret** 에서 3개 등록:

| Name | 값 |
|---|---|
| `GEMINI_API_KEY` | 3번의 키 |
| `TELEGRAM_BOT_TOKEN` | 4번의 토큰 |
| `TELEGRAM_CHAT_ID` | 4번의 Chat ID |

### 6. 웹페이지 켜기
**Settings → Pages** → Source: **Deploy from a branch** → Branch: `main` / `/(root)` → **Save**
1~3분 뒤 `https://<내아이디>.github.io/yt-trend-monitor/` 주소로 접속됩니다. 휴대폰에서는 **홈 화면에 추가**해 두면 앱처럼 쓸 수 있습니다.

### 7. 자동 실행 켜고 테스트
1. 저장소 **Actions** 탭 → 안내가 나오면 **I understand… enable** 클릭
2. 왼쪽 **Telegram Test** → **Run workflow** → 텔레그램에 테스트 메시지가 오면 성공

### 8. 웹페이지에서 채널을 추가할 수 있게 연결
웹페이지에서 채널 추가·삭제를 하려면 GitHub 토큰이 한 번 필요합니다.
1. GitHub 오른쪽 위 프로필 → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**
2. Expiration: 1년(최대), Repository access: **Only select repositories** → `yt-trend-monitor`
3. Permissions → Repository permissions:
   - **Contents: Read and write**
   - **Actions: Read and write**
4. 생성된 토큰(`github_pat_…`) 복사 → 웹페이지 **채널 관리 → 연결 설정**에 붙여넣고 저장
   (토큰은 그 브라우저에만 저장됩니다. PC와 휴대폰에서 각각 한 번씩 입력하세요.)

### 9. 우리 회사 취급 브랜드 입력
저장소의 `settings.json` → 연필 아이콘(편집) → `our_brands` 에 취급 브랜드를 넣고 저장:
```json
"our_brands": ["브랜드A", "브랜드B"],
```
여기 들어간 브랜드는 분석 결과에서 **★ 자사**로 표시되고, 웹페이지에서 '자사 브랜드 언급만' 필터로 모아볼 수 있습니다.

---

## 사용법
- **채널 추가**: 웹페이지 → 채널 관리 → 채널 링크 + 거래처명 + 거래처 성격 메모 → 추가하고 저장
  - 1~2분 뒤 자동 실행되어 해당 채널의 **최근 영상 1개**를 분석하고, 이후로는 새 영상만 분석합니다.
  - 거래처 메모를 구체적으로 쓸수록 '영업 시사점'이 정확해집니다.
- **지금 확인**: 6시간을 기다리지 않고 바로 확인하려면 채널 관리 → 지금 확인 실행
- **텔레그램 알림의 '📊 상세 분석'** 링크를 누르면 웹페이지의 해당 영상 분석이 바로 열립니다.

## 설정 (`settings.json`)
| 항목 | 기본값 | 설명 |
|---|---|---|
| `our_brands` | `[]` | 자사 취급 브랜드 |
| `gemini_model` | `gemini-3.8-flash` | 분석 모델. 오류 시 `gemini_fallback_model` 로 자동 전환 |
| `initial_backfill` | `1` | 채널 첫 등록 시 분석할 최근 영상 수 |
| `max_per_run` | `8` | 한 번에 분석할 최대 영상 수 (나머지는 다음 실행) |
| `max_age_days` | `14` | 이보다 오래된 영상은 분석하지 않음 |
| `skip_shorts` | `false` | `true` 면 쇼츠 제외 |

확인 주기를 바꾸려면 `.github/workflows/monitor.yml` 의 `cron` 을 수정합니다 (UTC 기준).

## 참고
- **공개 범위**: 무료 GitHub Pages는 공개 저장소에서만 동작하므로, 주소를 아는 사람은 분석 결과와 `channels.json`(거래처 메모)을 볼 수 있습니다. 검색엔진 노출은 막아두었습니다. 거래처 메모에 민감한 내용(매출, 단가 등)은 적지 마세요.
- **Gemini 무료 등급**: 하루 유튜브 영상 8시간 분량까지 무료이며, 무료 등급 입력 데이터는 Google 서비스 개선에 쓰일 수 있습니다. **공개 영상만** 분석됩니다(일부 공개·비공개 영상 제외).
- **AI 분석 한계**: 모델명·가격은 AI가 읽은 결과이므로, 견적·제안에 쓰기 전에 영상의 해당 시점(▶ 시간 링크)에서 한 번 확인하세요.
- 실행 기록은 **Actions** 탭에서, 오류 채널은 웹페이지 **채널 관리**에서 확인할 수 있습니다.
