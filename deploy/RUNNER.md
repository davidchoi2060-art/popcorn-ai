# 서버에 GitHub Actions 러너 붙이기 (배포·회귀 자동화)

**무엇을 하는 건가.** 서버 VM 안에 작은 실행기(러너)를 하나 깔아 둔다. 그러면 `main` 에
코드가 푸시될 때마다 **서버가 스스로** GitHub 에서 받아 배포하고, 회귀 세트도 버튼 하나로
돌릴 수 있다. 방화벽은 한 구멍도 열지 않는다 — 러너가 밖으로만 연결하기 때문이다.

**왜 이렇게 나눴나.** 러너는 리포의 워크플로 파일을 그대로 실행한다. 그래서 배포·재시작
같은 root 작업을 워크플로에 적으면, 리포에 푸시할 수 있는 사람은 누구나 서버에서 root
명령을 돌릴 수 있게 된다. 그래서 root 작업은 서버에 고정해 둔 `/usr/local/bin/popcorn-ci`
한 파일에 가두고, 러너 계정에는 그 파일의 세 가지 사용법만 허용한다. 워크플로를 어떻게
고쳐도 서버에서 할 수 있는 일은 그 셋을 벗어나지 못한다.

아래 §1~§4 는 서버에서, §5 는 GitHub 웹에서 한 번만 하면 된다.

---

## 1. 러너 전용 계정 만들기

권한이 거의 없는 계정을 따로 판다. `popcorn` 그룹에 **넣지 않는다** — 넣으면
`/etc/popcorn-ai.env` 의 DB 비밀번호를 읽을 수 있게 된다.

```bash
sudo useradd -m -s /bin/bash ghrunner
```

## 2. 고정 스크립트 설치

```bash
sudo install -m 755 -o root -g root /srv/popcorn-ai/deploy/popcorn-ci /usr/local/bin/popcorn-ci
sudo popcorn-ci verify          # 먼저 손으로 한 번 돌려 본다
```

> ⚠ 이 파일이 리포에서 바뀌면 위 `install` 을 **다시 실행해야** 반영된다.
> 자동으로 따라가지 않는 것이 이 구조의 핵심이다.

## 3. sudo 권한을 세 줄만 준다

```bash
sudo tee /etc/sudoers.d/popcorn-ci >/dev/null <<'EOF'
ghrunner ALL=(root) NOPASSWD: /usr/local/bin/popcorn-ci deploy
ghrunner ALL=(root) NOPASSWD: /usr/local/bin/popcorn-ci regression
ghrunner ALL=(root) NOPASSWD: /usr/local/bin/popcorn-ci verify
EOF
sudo chmod 440 /etc/sudoers.d/popcorn-ci
sudo visudo -c                  # "parsed OK" 가 나와야 한다
```

확인 — 허용한 것만 되고 나머지는 막혀야 한다:

```bash
sudo -u ghrunner sudo -n /usr/local/bin/popcorn-ci verify   # 된다
sudo -u ghrunner sudo -n systemctl restart popcorn-api      # 거절돼야 정상
```

## 4. 러너 설치

GitHub 에서 **Settings → Actions → Runners → New self-hosted runner → Linux / x64** 를 열면
그 화면에 다운로드 명령 세 줄과 **등록 토큰이 박힌 `./config.sh` 명령**이 나온다.
토큰은 한 시간 뒤 만료되니 그때 바로 쓴다.

```bash
sudo -u ghrunner -i          # ghrunner 계정으로 들어간다 (root 로 설치하면 러너가 거부한다)
mkdir -p ~/actions-runner && cd ~/actions-runner
# ↓ GitHub 화면의 curl · tar 두 줄을 그대로 붙여넣는다 (버전이 계속 바뀌므로 여기 적지 않는다)
```

내려받았으면 설정한다. **`--labels popcorn-vm` 을 반드시 붙인다** — 워크플로가 이 이름으로
러너를 찾는다.

```bash
./config.sh --url https://github.com/davidchoi2060-art/popcorn-ai \
            --token <GitHub 화면의 토큰> \
            --name popcorn-vm --labels popcorn-vm --unattended
exit                         # ghrunner 계정에서 나온다
```

부팅해도 계속 돌도록 서비스로 등록한다:

```bash
cd /home/ghrunner/actions-runner
sudo ./svc.sh install ghrunner
sudo ./svc.sh start
sudo ./svc.sh status          # active (running)
```

GitHub 의 Runners 화면에서 `popcorn-vm` 이 **Idle** 로 보이면 성공이다.

## 5. 공개 리포 안전장치 (GitHub 웹에서)

이 리포는 공개라, 남이 포크해서 올린 코드가 우리 서버 러너에서 돌지 않게 막아야 한다.

**Settings → Actions → General → Fork pull request workflows from outside collaborators**
→ **Require approval for all external contributors** 를 고르고 Save.

이 리포의 워크플로에는 `pull_request` 트리거가 없어서 이미 한 겹 막혀 있다. 위 설정은
두 번째 겹이다. **앞으로도 워크플로에 `pull_request` 를 넣지 않는다.**

---

## 쓰는 법

| 하고 싶은 것 | 방법 |
|---|---|
| 배포 | `main` 에 푸시하면 자동 (문서·`*.md` 만 바뀐 커밋은 건너뛴다) |
| 배포 + 회귀 | Actions → **배포** → Run workflow → `regression` 체크 |
| 회귀만 | Actions → **회귀 세트** → Run workflow |
| 결과 보기 | Actions 탭의 실행 기록. 회귀는 요약란에 마지막 30줄이 붙는다 |

회귀 세트를 자동으로 돌리지 않는 이유: 이 세트는 검사 과정에서 운영 Cloud SQL 에 검사용
행을 넣었다 지운다. 사장님 PC 에서 돌릴 때와 같은 DB 라 새로운 위험은 아니지만, 커밋마다
자동으로 건드릴 일은 아니라서 손으로 부르는 방식으로 뒀다.

## 되돌리기

```bash
cd /home/ghrunner/actions-runner && sudo ./svc.sh stop && sudo ./svc.sh uninstall
sudo -u ghrunner -i bash -c 'cd ~/actions-runner && ./config.sh remove --token <GitHub 화면의 제거 토큰>'
sudo rm -f /etc/sudoers.d/popcorn-ci /usr/local/bin/popcorn-ci
sudo userdel -r ghrunner
```

배포는 다시 `deploy/README.md` 의 수동 절차로 돌아간다.
