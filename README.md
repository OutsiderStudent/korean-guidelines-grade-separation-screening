# Korean Guidelines-Based Grade Separation Screening

**Traffic Volume and Capacity Assessment**  
한국어 프로그램명: **입체화검토** · 약칭: **K-GSS** · 버전: **v3.8.0**

made by NYH · yuhyun1245@gmail.com

국토교통부 「교차로 설계지침(2025)」과 「도로용량편람(2013)」을 참고하여 제작한 입체교차 개략검토 프로그램입니다.

> K-GSS is a Korean-guidelines-based desktop tool for screening intersection grade-separation needs using traffic volume and capacity.

국토교통부 「교차로 설계 지침(2025.06)」의 `1.4.2 교통량과 입체교차의 관계`에 따라 교통량과 용량의 A·B·C·D 영역을 검토하는 Windows 데스크톱 프로그램입니다.

## 주요 기능

- 3·4·5·6지 교차로 선택과 고정 방향 코드(SB, NB, WB, EB, SEB, SWB, NWB, NEB)
- 접근로별 편도 본선 차로수, 좌회전·직진·우회전 시간교통량, 중차량 비율 입력
- 기본 화면을 유지하면서 자동계수·직접계수와 P′ 가정을 조절하는 상세 보정 설정
- 4지는 정확히 4개 충돌쌍, 3·5·6지는 충돌쌍 확장검토 후 최악 영역을 최종 판정
- 71 mm × 71 mm 보고서용 그래프 클립보드 복사 및 PNG 저장
- 상세 그래프와 모든 그래프 일괄 저장
- 프로젝트 새로 만들기·열기·저장·다른 이름으로 저장(`.igr3`)
- `.igr3` 파일 더블클릭 시 K-GSS 실행과 동시에 해당 프로젝트 자동 불러오기
- 지침 원문 페이지, 적용 공식, 출처와 프로그램 가정을 확인하는 `지침·공식` 탭
- Noto Sans KR 글꼴과 전용 아이콘을 포함한 단일 portable EXE
- 실행 시 GitHub Release의 최신 버전을 자동 확인하고 SHA-256 검증 후 업데이트
- 현재 단계 표시, 화면 전환 페이드, 마우스·키보드 버튼 축소·스프링 복귀 효과 (`KGSS_REDUCE_MOTION=1`로 모션 끄기)

## 계산 원칙과 출처 구분

- A·B·C·D 경계, `C = 1,800 × 편도 본선 차로수`, P·P′ 구조 및 예시는 「교차로 설계 지침(2025.06)」 PDF 244~247쪽(인쇄면 235~238쪽)을 따릅니다.
- 자동 회전계수는 「도로용량편람(2013)」의 직진·좌·우 통합차로군 식 `f = 1/[1+PL(EL-1)+PR(ER-1)]`, 중차량계수는 식 8-39를 적용합니다.
- 상세 차로군·신호조건을 입력하지 않는 개략검토 기본값은 `EL=2.0`, `ER=1.5`, `EHV=1.8`이며 프로그램의 입력 확인 화면과 부록에 공개합니다.
- 별도 분석계수가 있으면 접근로별 통합 회전계수와 중차량계수를 직접 입력할 수 있습니다. 2025 지침 예제의 명시 계수는 직접 입력 회귀시험으로 q, C, P, P′ 및 영역 C를 재현합니다.
- P′ 기본값은 지침 예제의 `(C + 600) × 0.9 + 2 × 3,600 / 36`이며 상세 설정에서 근거값을 변경할 수 있습니다.
- 판정에는 백 단위 표시값이 아닌 원시 계산값을 사용합니다.
- 3·5·6지 결과는 지침에 직접 제시된 방식이 아니라 충돌 접근로 쌍에 대한 보수적 확장검토이며 화면에 이를 명시합니다.

이 프로그램은 기본계획 단계의 개략검토 도구이며 상세 신호교차로 용량분석을 대신하지 않습니다.

## 개발 실행

```powershell
python -m pip install -e .
python -m interchange_review
```

## 테스트와 EXE 빌드

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
python validation\scenario_validation.py
python validation\render_ui.py
.\build.ps1
```

빌드 결과: `dist\K-GSS_v3.8.0.exe`

Noto Sans KR은 SIL Open Font License 1.1로 포함되며 라이선스 원문은 `assets/NotoSansKR-OFL.txt`에 있습니다.
