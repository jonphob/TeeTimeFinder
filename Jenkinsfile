pipeline {
    agent any

    environment {
        DEPLOY_PATH = '/srv/apps/teetime_scraper'
        VENV_PATH   = "${DEPLOY_PATH}/.venv"
        SERVICE_NAME = 'teetime.timer'
    }

    stages {
        stage('Lint') {
            steps {
                sh '''
                    python3 -m venv .venv-ci
                    . .venv-ci/bin/activate
                    pip install --quiet flake8
                    flake8 scraper.py --max-line-length=120
                '''
            }
        }

        stage('Test') {
            steps {
                sh '''
                    . .venv-ci/bin/activate
                    pip install --quiet -r requirements.txt
                    python3 -m py_compile scraper.py
                    echo "Compile check passed"
                '''
            }
        }

        stage('Deploy') {
            when {
                branch 'main'
            }
            steps {
                sh '''
                    rsync -av --exclude='.git' --exclude='.venv-ci' --exclude='__pycache__' \
                        ./ ${DEPLOY_PATH}/

                    ${VENV_PATH}/bin/pip install --quiet -r ${DEPLOY_PATH}/requirements.txt

                    sudo systemctl daemon-reload
                    sudo systemctl restart ${SERVICE_NAME}
                    sudo systemctl is-active --quiet ${SERVICE_NAME} && echo "Timer active" || (echo "Timer failed to start" && exit 1)
                '''
            }
        }
    }

    post {
        always {
            sh 'rm -rf .venv-ci'
            cleanWs()
        }
        failure {
            echo "Pipeline failed on branch ${env.BRANCH_NAME}"
        }
        success {
            echo "Pipeline passed on branch ${env.BRANCH_NAME}"
        }
    }
}
