"""Optional demo stack: a minimal Fargate-backed AWS Batch environment plus a
deliberately buggy job definition (see demo/process_orders.py), so you can
watch the full failure -> diagnosis -> fix/reroute loop end to end without
touching a real production pipeline.
"""

from __future__ import annotations

from aws_cdk import Aws, CfnOutput, RemovalPolicy, Size, Stack
from aws_cdk import aws_batch as batch
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_s3 as s3
from constructs import Construct


class DemoStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        recovery_function: _lambda.IFunction,
        github_repo: str = "",
        entrypoint: str = "demo/process_orders.py",
        ref: str = "main",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        vpc = ec2.Vpc(
            self,
            "DemoVpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(name="Public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24)
            ],
        )

        repo = ecr.Repository(
            self,
            "DemoRepo",
            repository_name="agentic-batch-debug-demo",
            removal_policy=RemovalPolicy.DESTROY,
        )

        data_bucket = s3.Bucket(
            self,
            "DemoDataBucket",
            bucket_name=f"agentic-batch-debug-data-{Aws.ACCOUNT_ID}-{Aws.REGION}",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
        )
        data_bucket.grant_read_write(recovery_function)

        job_role = iam.Role(self, "DemoJobRole", assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"))
        data_bucket.grant_read(job_role)

        compute_env = batch.FargateComputeEnvironment(
            self,
            "DemoComputeEnv",
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            maxv_cpus=4,
        )

        job_queue = batch.JobQueue(self, "DemoJobQueue", job_queue_name="agentic-batch-debug-demo-queue")
        job_queue.add_compute_environment(compute_env, order=1)

        container = batch.EcsFargateContainerDefinition(
            self,
            "DemoContainer",
            image=ecs.ContainerImage.from_ecr_repository(repo, "latest"),
            cpu=1,
            memory=Size.mebibytes(2048),
            job_role=job_role,
            assign_public_ip=True,
            command=["python", "process_orders.py", "Ref::inputUri"],
        )

        # AWS Batch job definition tags are NOT inherited by jobs submitted from
        # them - the agent needs per-job tags, so submit_demo_job.sh passes
        # agentic-debug:repo/entrypoint/ref explicitly via `batch submit-job --tags`.
        job_definition = batch.EcsJobDefinition(
            self,
            "DemoJobDefinition",
            job_definition_name="agentic-batch-debug-demo-job",
            container=container,
            retry_attempts=1,
        )

        self.data_bucket = data_bucket
        self.job_queue = job_queue
        self.job_definition = job_definition
        self.repository = repo

        CfnOutput(self, "DemoEcrRepoUri", value=repo.repository_uri)
        CfnOutput(self, "DemoDataBucketName", value=data_bucket.bucket_name)
        CfnOutput(self, "DemoJobQueueName", value=job_queue.job_queue_name)
        CfnOutput(self, "DemoJobDefinitionName", value=job_definition.job_definition_name)
        # Exposed so submit_demo_job.sh can pass the exact agentic-debug:* tags at
        # `batch submit-job` time without hardcoding them in two places.
        CfnOutput(self, "DemoAgentRepoTag", value=github_repo or "UNSET-pass-c-githubRepo-at-deploy")
        CfnOutput(self, "DemoAgentEntrypointTag", value=entrypoint)
        CfnOutput(self, "DemoAgentRefTag", value=ref)
