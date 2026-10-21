# SY POS 기본 MP3 사운드

사용자가 첨부하고 용도를 지정한 원본 6개입니다. 2026-10-20 사용자가 **MP3 6개 모두 공개 배포에 포함**하도록 명시적으로 승인했습니다. 원본 오디오 바이트는 변경하지 않고 이벤트별로 연결했습니다.

| 이벤트 | 원본 파일 / 표시된 제작자 |
| --- | --- |
| 공 추첨 결과 표시 | freesound_community-winning-82808.mp3 · freesound_community |
| 행운의 숫자 메뉴 열기 | u_xmiiqyhi46-gamestart-272829.mp3 · u_xmiiqyhi46 |
| 로그인 성공 | freesound_community-lovelyboot1-103697.mp3 · freesound_community |
| 메시지 경고·알림 | liecio-message-alert-190042.mp3 · liecio |
| 왼쪽 마우스 클릭 | universfield-computer-mouse-click-02-383961.mp3 · universfield |
| 오른쪽 마우스로 실제 메뉴 열기 | creatorshome-sharp-pop-328170.mp3 · creatorshome |

파일명에 표시된 제작자명을 보존합니다. 별도 원본 라이선스 문서는 첨부되지 않았으므로 이 안내는 CC0·권리 양도·무제한 재배포 허락을 새로 주장하지 않습니다. 외부 재사용 시 원본 사용 조건을 확인하세요.

각 파일의 원본 SHA256은 `pos2/audio_defaults.py`에 고정되어 있으며 빌드와 실행 시 검사합니다. 허용된 위치·이름·바이트가 일치하는 이 6개만 공개 ZIP에 포함합니다. 사용자가 나중에 선택한 다른 음원과 PC별 설정은 배포하지 않습니다. 음악 자동 다운로드·외부 전송은 없습니다.

## 마우스 효과음 저지연 PCM

원본 MP3 6개는 변경하지 않았습니다. 위에서 승인된 왼쪽 클릭·오른쪽 메뉴 MP3를 PCM 16-bit WAV로 해제하고 앞뒤 무음만 줄인 `mouse-click-ready.wav`, `mouse-context-ready.wav` 2개를 함께 제공합니다. 새 음원을 추가한 것이 아니라 같은 승인 음원의 빠른 재생용 사본입니다. 해당 원본과 일치하는 개인 PC 사본에도 적용하며, 다른 사용자 음원을 이 파생본으로 바꾸지는 않습니다. PCM의 SHA256도 `MOUSE_PCM`으로 고정해 빌드 시 검증합니다.

재현: 원본별 FFmpeg 입력에 `silenceremove=start_periods=1:start_duration=0:start_threshold=-50dB:start_silence=0.003:stop_periods=1:stop_duration=0.08:stop_threshold=-50dB:stop_silence=0.02`, `-map_metadata -1 -bitexact -c:a pcm_s16le`를 적용합니다. 원래 샘플레이트·스테레오를 유지하며 음량을 정규화하거나 증폭하지 않습니다. 런타임 FFmpeg 설치·외부 다운로드는 필요 없습니다.
