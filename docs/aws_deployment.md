# AWS Deployment Checklist

This is a placeholder checklist for a future AWS deployment pass.

- Choose hosting for the frontend, for example S3 + CloudFront or Amplify.
- Choose hosting for the Flask backend, for example Elastic Beanstalk, ECS, or EC2.
- Provision MySQL with Amazon RDS.
- Move secrets into AWS-managed environment variables or Secrets Manager.
- Configure CORS for the deployed frontend origin.
- Serve uploads from durable storage, preferably S3, instead of local disk.
- Add HTTPS and set the session cookie `Secure` attribute.
- Add health checks, logs, backups, and monitoring.
