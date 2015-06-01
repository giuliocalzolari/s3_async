**Beta Version**

Execute a "aws s3 sync" on every change to upload on s3 bucket and notify to download the latest contest to all notificator.

In this way you a have a perfect copy of a folder on every instances in asyncronous way without waiting the crontab execution of "aws s3 sync" and a full backup on S3


this is an example of config.yaml

	basedir: "/git/tool/s3_async/test_scan"
	grace_period: 3
	retry_notify: 60
	max_retry: 4

	replicator:
	 bucket1:
	  status: "disable"
	  url: "s3://s3-eu-west-1.amazonaws.com"
	  bucket: "giulio-bk"
	  acces_key: "....."
	  secret_key: "....."

	notificator:
	 ec2web:
	  status: "enable"
	  url: "ec2://web-autodiscovery"
	  refresh: 60
	  match_ec2: "web-[0-9]+"
	  acces_key: "key123"
	  secret_key: "secter1234"
  	  mapping: "public_ip_address"  # private_ip_address , public_ip_address , public_dns_name , private_dns_name 
      region: "eu-central-1"
      private_key: "/path/.ssh/private.key"
      username: "ubuntu"

	 ec2test1:
	  status: "enable"
	  url: "1.1.1.1"
	  private_key: "/path/.ssh/private.key"
	  username: "ubuntu"

	 ec2test2:
	  status: "enable"
	  url: "2.2.2.2"
	  private_key: "/path/.ssh/private.key"
	  username: "ubuntu"







