pipeline {
    agent any

    triggers {
        githubPush()
    }

    environment {
        DEPLOY_PATH = '/srv/apps/teetime_scraper'
        VENV_PATH   = "${DEPLOY_PATH}/.venv"
        SERVICE_NAME = 'teetime.timer'
    }

    stages {
        stage('Test') {
            steps {
                sh '''
                    python3 -m py_compile scraper.py
                    echo "Compile check passed"
                '''
            }
        }

        stage('Deploy') {
            steps {
                sh '''
                    rsync -av --exclude='.git' --exclude='.venv-ci' --exclude='__pycache__' \
                        ./ ${DEPLOY_PATH}/

                    ${VENV_PATH}/bin/python3 -m pip install --quiet -r ${DEPLOY_PATH}/requirements.txt

                    sudo systemctl daemon-reload
                    sudo systemctl restart ${SERVICE_NAME}
                    sudo systemctl is-active --quiet ${SERVICE_NAME} && echo "Timer active" || (echo "Timer failed to start" && exit 1)
                '''
            }
        }
    }

    post {
        always {
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
