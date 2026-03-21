pipeline {
    agent any

    triggers {
        githubPush()
    }

    environment {
        DEPLOY_PATH = '/srv/apps/teetime_scraper'
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
                    rsync -av \
                        --exclude='.git' \
                        --exclude='__pycache__' \
                        --exclude='.claude' \
                        --exclude='CLAUDE.md' \
                        --exclude='PRD.md' \
                        --exclude='PRD.json' \
                        --exclude='Jenkinsfile' \
                        --exclude='grafana_dashboard.json' \
                        --exclude='progress.txt' \
                        --exclude='.gitignore' \
                        --exclude='debug_output.html' \
                        ./ ${DEPLOY_PATH}/
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
