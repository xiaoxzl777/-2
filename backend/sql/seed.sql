-- 种子数据：技能同义词词典 + 岗位模板
-- 本文件由 scripts/dump_seed.py 从 data/skills_seed.csv 与 data/job_templates.json 自动生成，请勿手改。
-- 在 MySQL 中执行；可重复执行（skills 表先清空再插入，岗位模板按标题更新）。需先执行 schema.sql。

SET NAMES utf8mb4;  -- 不写的话 docker 首次建库导入时中文会变乱码（镜像执行 .sql 的客户端不是 utf8mb4）
USE `resume_ai`;

DELETE FROM skills;

INSERT INTO skills (id, canonical_name, category, aliases) VALUES
  (1, 'Java', 'language', '["Java语言", "JavaSE", "Java SE", "JDK"]'),
  (2, 'Python', 'language', '["python3"]'),
  (3, 'C++', 'language', '["CPP", "C plus plus", "c++11", "C++17"]'),
  (4, 'C', 'language', '["C语言"]'),
  (5, 'C#', 'language', '["CSharp", "C Sharp"]'),
  (6, 'Go', 'language', '["Golang", "Go语言"]'),
  (7, 'Rust', 'language', '["Rust语言"]'),
  (8, 'JavaScript', 'language', '["JS", "ECMAScript", "ES6", "java script"]'),
  (9, 'TypeScript', 'language', '["TS"]'),
  (10, 'Kotlin', 'language', '[]'),
  (11, 'Swift', 'language', '[]'),
  (12, 'PHP', 'language', '[]'),
  (13, 'Scala', 'language', '[]'),
  (14, 'SQL', 'language', '["结构化查询语言"]'),
  (15, 'Shell', 'language', '["Bash", "bash脚本", "Shell脚本", "shell script"]'),
  (16, 'HTML', 'language', '["HTML5"]'),
  (17, 'CSS', 'language', '["CSS3"]'),
  (18, 'Spring', 'backend', '["Spring Framework", "Spring框架", "SpringFramework"]'),
  (19, 'Spring Boot', 'backend', '["SpringBoot", "spring-boot"]'),
  (20, 'Spring Cloud', 'backend', '["SpringCloud", "spring-cloud"]'),
  (21, 'Spring MVC', 'backend', '["SpringMVC", "spring-mvc"]'),
  (22, 'Spring Security', 'backend', '["SpringSecurity"]'),
  (23, 'MyBatis', 'backend', '["iBatis"]'),
  (24, 'MyBatis-Plus', 'backend', '["MybatisPlus", "MyBatis Plus"]'),
  (25, 'Hibernate', 'backend', '[]'),
  (26, 'JPA', 'backend', '["Spring Data JPA", "Java Persistence API"]'),
  (27, 'Netty', 'backend', '[]'),
  (28, 'Dubbo', 'backend', '["Apache Dubbo"]'),
  (29, 'gRPC', 'backend', '[]'),
  (30, 'Django', 'backend', '[]'),
  (31, 'Flask', 'backend', '[]'),
  (32, 'FastAPI', 'backend', '["Fast API"]'),
  (33, 'Gin', 'backend', '["Gin框架", "gin-gonic"]'),
  (34, 'Node.js', 'backend', '["NodeJS"]'),
  (35, 'Express', 'backend', '["Express.js", "expressjs"]'),
  (36, 'NestJS', 'backend', '["Nest.js"]'),
  (37, '.NET', 'backend', '["dotnet", ".NET Core", "ASP.NET", "ASP.NET Core"]'),
  (38, 'Tomcat', 'backend', '["Apache Tomcat"]'),
  (39, 'JVM', 'backend', '["Java虚拟机", "JVM调优"]'),
  (40, '多线程', 'backend', '["并发编程", "JUC", "多线程编程", "concurrency"]'),
  (41, '微服务', 'backend', '["微服务架构", "Microservices", "microservice", "Micro Service"]'),
  (42, 'RESTful API', 'backend', '["REST", "RESTful", "REST API", "Restful接口"]'),
  (43, '分布式', 'backend', '["分布式系统", "分布式架构", "distributed system"]'),
  (44, '设计模式', 'backend', '["Design Patterns", "design pattern"]'),
  (45, 'Nacos', 'backend', '[]'),
  (46, 'Sentinel', 'backend', '[]'),
  (47, 'Seata', 'backend', '[]'),
  (48, 'Zookeeper', 'backend', '["zk"]'),
  (49, 'RabbitMQ', 'middleware', '["Rabbit MQ"]'),
  (50, 'Kafka', 'middleware', '["Apache Kafka"]'),
  (51, 'RocketMQ', 'middleware', '["Rocket MQ"]'),
  (52, '消息队列', 'middleware', '["MQ", "Message Queue", "消息中间件"]'),
  (53, 'Elasticsearch', 'middleware', '["ES搜索", "elastic search", "ELK"]'),
  (54, 'Nginx', 'middleware', '[]'),
  (55, 'MySQL', 'database', '["My SQL", "MySQL数据库"]'),
  (56, 'PostgreSQL', 'database', '["Postgres", "pgsql"]'),
  (57, 'Oracle', 'database', '["Oracle数据库"]'),
  (58, 'SQL Server', 'database', '["SQLServer", "MSSQL", "MS SQL"]'),
  (59, 'SQLite', 'database', '["sqlite3"]'),
  (60, 'Redis', 'database', '["Redis缓存", "Redis集群", "Redis Cluster"]'),
  (61, 'MongoDB', 'database', '["Mongo"]'),
  (62, 'Memcached', 'database', '["memcache"]'),
  (63, 'ClickHouse', 'database', '[]'),
  (64, 'HBase', 'database', '[]'),
  (65, 'Milvus', 'database', '[]'),
  (66, 'Chroma', 'database', '["ChromaDB"]'),
  (67, 'pgvector', 'database', '[]'),
  (68, '向量数据库', 'database', '["Vector Database", "vector db", "向量库"]'),
  (69, '索引优化', 'database', '["SQL优化", "慢查询优化", "SQL调优", "数据库优化"]'),
  (70, '分库分表', 'database', '["ShardingSphere", "Sharding-JDBC", "sharding"]'),
  (71, 'React', 'frontend', '["ReactJS", "React.js", "React18"]'),
  (72, 'Vue', 'frontend', '["Vue.js", "vuejs", "Vue2", "Vue3"]'),
  (73, 'Angular', 'frontend', '["AngularJS"]'),
  (74, 'Next.js', 'frontend', '["NextJS"]'),
  (75, 'Nuxt', 'frontend', '["Nuxt.js", "nuxtjs"]'),
  (76, 'Redux', 'frontend', '["Redux Toolkit"]'),
  (77, 'Zustand', 'frontend', '[]'),
  (78, 'Pinia', 'frontend', '[]'),
  (79, 'Vuex', 'frontend', '[]'),
  (80, 'Webpack', 'frontend', '[]'),
  (81, 'Vite', 'frontend', '[]'),
  (82, 'Tailwind CSS', 'frontend', '["Tailwind", "tailwindcss"]'),
  (83, 'Sass', 'frontend', '["SCSS", "Less"]'),
  (84, 'Element UI', 'frontend', '["ElementUI", "Element Plus", "element-ui", "element-plus"]'),
  (85, 'Ant Design', 'frontend', '["antd", "AntDesign", "Ant Design Vue"]'),
  (86, 'shadcn/ui', 'frontend', '["shadcn"]'),
  (87, 'ECharts', 'frontend', '["Apache ECharts"]'),
  (88, 'D3.js', 'frontend', '["D3"]'),
  (89, 'jQuery', 'frontend', '[]'),
  (90, 'Axios', 'frontend', '[]'),
  (91, '微信小程序', 'frontend', '["小程序", "小程序开发", "微信小程序开发"]'),
  (92, 'uni-app', 'frontend', '["uniapp"]'),
  (93, 'Flutter', 'mobile', '[]'),
  (94, 'React Native', 'mobile', '["ReactNative"]'),
  (95, 'Android', 'mobile', '["Android开发", "安卓", "安卓开发"]'),
  (96, 'iOS', 'mobile', '["iOS开发"]'),
  (97, 'Docker', 'devops', '["Docker容器", "容器化"]'),
  (98, 'Kubernetes', 'devops', '["K8s"]'),
  (99, 'Docker Compose', 'devops', '["docker-compose"]'),
  (100, 'Jenkins', 'devops', '[]'),
  (101, 'GitHub Actions', 'devops', '["GitHub Action"]'),
  (102, 'CI/CD', 'devops', '["CICD", "持续集成", "持续部署", "持续交付"]'),
  (103, 'Git', 'tool', '["Git版本控制", "GitLab", "GitHub"]'),
  (104, 'Maven', 'tool', '[]'),
  (105, 'Gradle', 'tool', '[]'),
  (106, 'Linux', 'devops', '["CentOS", "Ubuntu", "Linux运维", "Linux系统"]'),
  (107, 'Prometheus', 'devops', '[]'),
  (108, 'Grafana', 'devops', '[]'),
  (109, '阿里云', 'devops', '["Aliyun", "阿里云ECS", "阿里云OSS"]'),
  (110, 'AWS', 'devops', '["Amazon Web Services", "亚马逊云"]'),
  (111, '腾讯云', 'devops', '["Tencent Cloud"]'),
  (112, 'Postman', 'tool', '[]'),
  (113, 'JMeter', 'tool', '["压力测试", "压测"]'),
  (114, 'JUnit', 'tool', '["junit5", "单元测试"]'),
  (115, 'pytest', 'tool', '[]'),
  (116, 'Selenium', 'tool', '["自动化测试"]'),
  (117, 'Swagger', 'tool', '["OpenAPI", "Knife4j"]'),
  (118, '机器学习', 'ai', '["Machine Learning", "ML"]'),
  (119, '深度学习', 'ai', '["Deep Learning", "DL", "神经网络"]'),
  (120, 'PyTorch', 'ai', '["torch"]'),
  (121, 'TensorFlow', 'ai', '["Keras"]'),
  (122, 'scikit-learn', 'ai', '["sklearn", "scikit learn"]'),
  (123, '自然语言处理', 'ai', '["NLP", "Natural Language Processing"]'),
  (124, '计算机视觉', 'ai', '["CV方向", "Computer Vision", "图像识别"]'),
  (125, 'OpenCV', 'ai', '["cv2"]'),
  (126, '大语言模型', 'ai', '["LLM", "大模型", "LLMs", "Large Language Model", "大模型应用"]'),
  (127, 'RAG', 'ai', '["检索增强生成", "Retrieval-Augmented Generation", "检索增强"]'),
  (128, 'Agent', 'ai', '["AI Agent", "智能体", "Agent开发", "多智能体"]'),
  (129, 'LangChain', 'ai', '[]'),
  (130, 'LangGraph', 'ai', '[]'),
  (131, 'LlamaIndex', 'ai', '["Llama Index"]'),
  (132, 'Prompt Engineering', 'ai', '["提示词工程", "Prompt工程", "prompt设计", "提示工程"]'),
  (133, '微调', 'ai', '["Fine-tuning", "fine tuning", "LoRA", "SFT", "模型微调"]'),
  (134, 'Transformer', 'ai', '["Transformers", "BERT", "注意力机制"]'),
  (135, 'Hugging Face', 'ai', '["HuggingFace"]'),
  (136, 'Embedding', 'ai', '["向量化", "文本向量"]'),
  (137, 'vLLM', 'ai', '[]'),
  (138, 'Ollama', 'ai', '[]'),
  (139, 'YOLO', 'ai', '["YOLOv5", "YOLOv8"]'),
  (140, '推荐系统', 'ai', '["推荐算法", "Recommender System"]'),
  (141, 'NumPy', 'data', '[]'),
  (142, 'Pandas', 'data', '[]'),
  (143, 'Matplotlib', 'data', '["Seaborn"]'),
  (144, 'Spark', 'data', '["Apache Spark", "PySpark"]'),
  (145, 'Hadoop', 'data', '["HDFS", "MapReduce"]'),
  (146, 'Flink', 'data', '["Apache Flink"]'),
  (147, 'Hive', 'data', '["HiveSQL"]'),
  (148, '数据分析', 'data', '["Data Analysis", "数据挖掘"]'),
  (149, '爬虫', 'data', '["网络爬虫", "Scrapy", "数据采集"]'),
  (150, '数据结构与算法', 'cs', '["数据结构", "算法", "LeetCode", "Data Structures"]'),
  (151, '操作系统', 'cs', '["OS原理", "Operating System"]'),
  (152, '计算机网络', 'cs', '["TCP/IP", "HTTP", "HTTPS", "网络协议", "HTTP协议"]'),
  (153, 'WebSocket', 'cs', '["WS长连接"]'),
  (154, 'OAuth2', 'cs', '["OAuth", "OAuth 2.0", "单点登录", "SSO"]'),
  (155, 'JWT', 'cs', '["Json Web Token", "token鉴权"]'),
  (156, 'Excel', 'ops', '["数据透视表", "透视表", "VLOOKUP"]'),
  (157, 'PPT', 'ops', '["PowerPoint", "幻灯片"]'),
  (158, 'Photoshop', 'ops', '["PS"]'),
  (159, 'Premiere', 'ops', '["Adobe Premiere", "Premiere Pro"]'),
  (160, '剪映', 'ops', '["CapCut", "剪映专业版"]'),
  (161, '稿定设计', 'ops', '["稿定", "Canva", "可画"]'),
  (162, '秀米', 'ops', '["秀米编辑器"]'),
  (163, '135编辑器', 'ops', '["135 编辑器"]'),
  (164, '小红书', 'ops', '["小红书运营"]'),
  (165, '抖音', 'ops', '["抖音运营", "Douyin"]'),
  (166, '微信公众号', 'ops', '["公众号", "公众号运营", "微信公众平台"]'),
  (167, '视频号', 'ops', '["微信视频号"]'),
  (168, '微博', 'ops', '["微博运营", "Weibo"]'),
  (169, 'B站', 'ops', '["哔哩哔哩", "bilibili"]'),
  (170, '知乎', 'ops', '["知乎运营"]'),
  (171, '快手', 'ops', '["快手运营"]'),
  (172, '直播运营', 'ops', '["直播带货", "带货直播"]'),
  (173, '社群运营', 'ops', '["社群", "微信社群"]'),
  (174, '私域运营', 'ops', '["私域", "私域流量"]'),
  (175, '用户增长', 'ops', '["增长黑客", "Growth Hacking", "拉新"]'),
  (176, 'A/B 测试', 'ops', '["A/B测试", "AB测试", "AB Test", "A/B Test", "ABTest"]'),
  (177, 'SEO', 'ops', '["搜索引擎优化"]'),
  (178, 'SEM', 'ops', '["搜索引擎营销", "竞价推广"]'),
  (179, '活动策划', 'ops', '["活动运营", "活动执行"]'),
  (180, '内容策划', 'ops', '["选题策划", "内容运营"]'),
  (181, '文案写作', 'ops', '["文案撰写", "新媒体写作"]'),
  (182, '短视频运营', 'ops', '["短视频", "短视频脚本", "短视频剪辑"]'),
  (183, 'KOL 投放', 'ops', '["KOL", "KOC", "达人投放"]'),
  (184, '用户画像', 'ops', '["人群画像"]'),
  (185, '漏斗分析', 'ops', '["转化漏斗", "漏斗模型"]'),
  (186, '留存分析', 'ops', '["用户留存", "留存率"]'),
  (187, 'AARRR', 'ops', '["AARRR模型", "海盗模型"]'),
  (188, 'RFM', 'ops', '["RFM模型"]'),
  (189, '神策数据', 'ops', '["神策", "Sensors Data"]'),
  (190, 'Google Analytics', 'ops', '["谷歌分析"]'),
  (191, '飞书', 'ops', '["Feishu", "Lark"]');

ALTER TABLE skills AUTO_INCREMENT = 192;

-- 岗位模板：按标题更新，不删除重建（投递记录按 id 引用岗位，删了会连带删掉投递）
UPDATE jobs SET is_deleted = 1 WHERE is_template = 1 AND title NOT IN ('后端开发实习生（Java）', '后端开发实习生（Python / Go）', '前端开发实习生', '算法实习生（机器学习）', 'AI 应用开发实习生（大模型）', '测试开发实习生', '数据分析实习生', '内容运营实习生（新媒体）', '用户运营实习生');

SET @raw = '岗位职责：
1. 参与业务系统的后端开发，负责接口设计、编码实现和单元测试；
2. 参与数据库表结构设计和 SQL 优化，协助排查线上问题；
3. 与前端、测试同学配合，按迭代计划交付需求。

任职要求：
1. 本科及以上学历在读，计算机、软件工程等相关专业；
2. Java 基础扎实，了解集合、多线程和 JVM 的基本原理；
3. 熟悉 Spring Boot，用过 MyBatis 或 JPA 等持久层框架；
4. 熟悉 MySQL，了解索引和事务，能写出规范的 SQL；
5. 了解 Redis 的常用数据结构和缓存使用场景；
6. 数据结构与算法基础扎实，了解计算机网络和操作系统；
7. 会用 Git 协作开发，能在 Linux 环境下完成日常开发和部署。

加分项：
1. 了解 RabbitMQ 或 Kafka 等消息队列；
2. 了解 Spring Cloud 等微服务框架；
3. 有完整的后端项目经历（课程设计、开源项目或实习均可）。

我们希望你：
学习能力强，有良好的沟通能力和团队协作意识。';
SET @reqs = '[{"id": 1, "req_type": "hard", "category": "education", "content": "本科及以上学历在读，计算机、软件工程等相关专业", "skill": null, "skill_id": null, "weight": 1.0, "quote": "本科及以上学历在读，计算机、软件工程等相关专业", "char_start": 106, "char_end": 129}, {"id": 2, "req_type": "hard", "category": "skill", "content": "Java 基础扎实", "skill": "Java", "skill_id": 1, "weight": 1.0, "quote": "Java 基础扎实，了解集合、多线程和 JVM 的基本原理", "char_start": 134, "char_end": 163}, {"id": 3, "req_type": "hard", "category": "skill", "content": "熟悉 Spring Boot", "skill": "Spring Boot", "skill_id": 19, "weight": 1.0, "quote": "熟悉 Spring Boot，用过 MyBatis 或 JPA 等持久层框架", "char_start": 168, "char_end": 206}, {"id": 4, "req_type": "hard", "category": "skill", "content": "用过 MyBatis 或 JPA 等持久层框架", "skill": null, "skill_id": null, "weight": 1.0, "quote": "用过 MyBatis 或 JPA 等持久层框架", "char_start": 183, "char_end": 206}, {"id": 5, "req_type": "hard", "category": "skill", "content": "熟悉 MySQL，了解索引和事务", "skill": "MySQL", "skill_id": 55, "weight": 1.0, "quote": "熟悉 MySQL，了解索引和事务，能写出规范的 SQL", "char_start": 211, "char_end": 238}, {"id": 6, "req_type": "hard", "category": "skill", "content": "了解 Redis 的常用数据结构和缓存使用场景", "skill": "Redis", "skill_id": 60, "weight": 1.0, "quote": "了解 Redis 的常用数据结构和缓存使用场景", "char_start": 243, "char_end": 266}, {"id": 7, "req_type": "hard", "category": "skill", "content": "数据结构与算法基础扎实", "skill": "数据结构与算法", "skill_id": 150, "weight": 1.0, "quote": "数据结构与算法基础扎实，了解计算机网络和操作系统", "char_start": 271, "char_end": 295}, {"id": 8, "req_type": "hard", "category": "skill", "content": "了解计算机网络", "skill": "计算机网络", "skill_id": 152, "weight": 1.0, "quote": "数据结构与算法基础扎实，了解计算机网络和操作系统", "char_start": 271, "char_end": 295}, {"id": 9, "req_type": "hard", "category": "skill", "content": "了解操作系统", "skill": "操作系统", "skill_id": 151, "weight": 1.0, "quote": "数据结构与算法基础扎实，了解计算机网络和操作系统", "char_start": 271, "char_end": 295}, {"id": 10, "req_type": "hard", "category": "skill", "content": "会用 Git 协作开发", "skill": "Git", "skill_id": 103, "weight": 1.0, "quote": "会用 Git 协作开发，能在 Linux 环境下完成日常开发和部署", "char_start": 300, "char_end": 333}, {"id": 11, "req_type": "hard", "category": "skill", "content": "能在 Linux 环境下完成日常开发和部署", "skill": "Linux", "skill_id": 106, "weight": 1.0, "quote": "会用 Git 协作开发，能在 Linux 环境下完成日常开发和部署", "char_start": 300, "char_end": 333}, {"id": 12, "req_type": "plus", "category": "skill", "content": "了解 RabbitMQ 或 Kafka 等消息队列", "skill": null, "skill_id": null, "weight": 0.5, "quote": "了解 RabbitMQ 或 Kafka 等消息队列", "char_start": 344, "char_end": 369}, {"id": 13, "req_type": "plus", "category": "skill", "content": "了解 Spring Cloud 等微服务框架", "skill": "Spring Cloud", "skill_id": 20, "weight": 0.5, "quote": "了解 Spring Cloud 等微服务框架", "char_start": 374, "char_end": 396}, {"id": 14, "req_type": "plus", "category": "experience", "content": "有完整的后端项目经历", "skill": null, "skill_id": null, "weight": 0.5, "quote": "有完整的后端项目经历（课程设计、开源项目或实习均可）", "char_start": 401, "char_end": 427}, {"id": 15, "req_type": "soft", "category": "other", "content": "学习能力强", "skill": null, "skill_id": null, "weight": 0.3, "quote": "学习能力强，有良好的沟通能力和团队协作意识", "char_start": 437, "char_end": 458}]';
UPDATE jobs SET domain = 'cs', raw_text = @raw, requirements = @reqs, parse_status = 'success', is_deleted = 0
  WHERE is_template = 1 AND title = '后端开发实习生（Java）';
INSERT INTO jobs (user_id, is_template, title, domain, raw_text, requirements, parse_status)
  SELECT NULL, 1, '后端开发实习生（Java）', 'cs', @raw, @reqs, 'success' FROM DUAL
  WHERE NOT EXISTS (SELECT 1 FROM jobs WHERE is_template = 1 AND title = '后端开发实习生（Java）');

SET @raw = '岗位职责：
1. 参与服务端功能开发，设计并实现 RESTful API；
2. 参与服务的容器化部署、监控和性能优化；
3. 编写技术文档，参与代码评审。

任职要求：
1. 本科及以上学历在读，计算机相关专业；
2. 熟练掌握 Python 或 Go 任一门语言即可；
3. 熟悉至少一种 Web 框架，如 FastAPI、Django 或 Gin；
4. 熟悉 MySQL，了解 Redis 的使用；
5. 了解 HTTP 协议和 RESTful API 设计规范；
6. 会用 Docker 打包和部署服务，熟悉 Linux 常用命令；
7. 熟悉 Git 的日常使用。

加分项：
1. 了解异步编程、消息队列或 gRPC；
2. 有 Kubernetes 使用经验；
3. 在 GitHub 上有自己的开源项目或贡献。

我们希望你：
对技术有热情，做事认真负责，能主动沟通进度和问题。';
SET @reqs = '[{"id": 1, "req_type": "hard", "category": "education", "content": "本科及以上学历在读，计算机相关专业", "skill": null, "skill_id": null, "weight": 1.0, "quote": "本科及以上学历在读，计算机相关专业", "char_start": 89, "char_end": 106}, {"id": 2, "req_type": "hard", "category": "skill", "content": "熟练掌握 Python 或 Go 任一门语言", "skill": null, "skill_id": null, "weight": 1.0, "quote": "熟练掌握 Python 或 Go 任一门语言即可", "char_start": 111, "char_end": 135}, {"id": 3, "req_type": "hard", "category": "skill", "content": "熟悉至少一种 Web 框架（FastAPI、Django 或 Gin）", "skill": null, "skill_id": null, "weight": 1.0, "quote": "熟悉至少一种 Web 框架，如 FastAPI、Django 或 Gin", "char_start": 140, "char_end": 176}, {"id": 4, "req_type": "hard", "category": "skill", "content": "熟悉 MySQL", "skill": "MySQL", "skill_id": 55, "weight": 1.0, "quote": "熟悉 MySQL，了解 Redis 的使用", "char_start": 181, "char_end": 202}, {"id": 5, "req_type": "hard", "category": "skill", "content": "了解 Redis 的使用", "skill": "Redis", "skill_id": 60, "weight": 1.0, "quote": "熟悉 MySQL，了解 Redis 的使用", "char_start": 181, "char_end": 202}, {"id": 6, "req_type": "hard", "category": "skill", "content": "了解 HTTP 协议", "skill": "HTTP", "skill_id": 152, "weight": 1.0, "quote": "了解 HTTP 协议和 RESTful API 设计规范", "char_start": 207, "char_end": 235}, {"id": 7, "req_type": "hard", "category": "skill", "content": "了解 RESTful API 设计规范", "skill": "RESTful API", "skill_id": 42, "weight": 1.0, "quote": "了解 HTTP 协议和 RESTful API 设计规范", "char_start": 207, "char_end": 235}, {"id": 8, "req_type": "hard", "category": "skill", "content": "会用 Docker 打包和部署服务", "skill": "Docker", "skill_id": 97, "weight": 1.0, "quote": "会用 Docker 打包和部署服务，熟悉 Linux 常用命令", "char_start": 240, "char_end": 271}, {"id": 9, "req_type": "hard", "category": "skill", "content": "熟悉 Linux 常用命令", "skill": "Linux", "skill_id": 106, "weight": 1.0, "quote": "会用 Docker 打包和部署服务，熟悉 Linux 常用命令", "char_start": 240, "char_end": 271}, {"id": 10, "req_type": "hard", "category": "skill", "content": "熟悉 Git 的日常使用", "skill": "Git", "skill_id": 103, "weight": 1.0, "quote": "熟悉 Git 的日常使用", "char_start": 276, "char_end": 288}, {"id": 11, "req_type": "plus", "category": "skill", "content": "了解异步编程、消息队列或 gRPC", "skill": null, "skill_id": null, "weight": 0.5, "quote": "了解异步编程、消息队列或 gRPC", "char_start": 299, "char_end": 316}, {"id": 12, "req_type": "plus", "category": "skill", "content": "有 Kubernetes 使用经验", "skill": "Kubernetes", "skill_id": 98, "weight": 0.5, "quote": "有 Kubernetes 使用经验", "char_start": 321, "char_end": 338}, {"id": 13, "req_type": "plus", "category": "experience", "content": "在 GitHub 上有自己的开源项目或贡献", "skill": null, "skill_id": null, "weight": 0.5, "quote": "在 GitHub 上有自己的开源项目或贡献", "char_start": 343, "char_end": 364}, {"id": 14, "req_type": "soft", "category": "other", "content": "对技术有热情，做事认真负责，能主动沟通进度和问题", "skill": null, "skill_id": null, "weight": 0.3, "quote": "对技术有热情，做事认真负责，能主动沟通进度和问题", "char_start": 374, "char_end": 398}]';
UPDATE jobs SET domain = 'cs', raw_text = @raw, requirements = @reqs, parse_status = 'success', is_deleted = 0
  WHERE is_template = 1 AND title = '后端开发实习生（Python / Go）';
INSERT INTO jobs (user_id, is_template, title, domain, raw_text, requirements, parse_status)
  SELECT NULL, 1, '后端开发实习生（Python / Go）', 'cs', @raw, @reqs, 'success' FROM DUAL
  WHERE NOT EXISTS (SELECT 1 FROM jobs WHERE is_template = 1 AND title = '后端开发实习生（Python / Go）');

SET @raw = '岗位职责：
1. 负责 Web 页面和中后台系统的前端开发，还原设计稿并保证交互体验；
2. 与后端同学对接接口，完成数据联调；
3. 参与前端组件的封装和性能优化。

任职要求：
1. 本科及以上学历在读，计算机相关专业优先；
2. 熟悉 HTML、CSS 和 JavaScript，了解 ES6 及以上语法；
3. 熟悉 React 或 Vue 其中一种框架，理解组件化开发；
4. 了解 TypeScript，能在项目中使用；
5. 了解 Vite 或 Webpack 等前端构建工具；
6. 了解 HTTP 协议和浏览器的基本工作原理；
7. 会用 Git 协作开发。

加分项：
1. 有移动端适配或微信小程序开发经验；
2. 用过 ECharts 等可视化库；
3. 有个人作品、技术博客或开源项目。

我们希望你：
对界面细节和用户体验敏感，学习能力强，善于沟通。';
SET @reqs = '[{"id": 1, "req_type": "hard", "category": "education", "content": "本科及以上学历在读", "skill": null, "skill_id": null, "weight": 1.0, "quote": "本科及以上学历在读，计算机相关专业优先", "char_start": 94, "char_end": 113}, {"id": 2, "req_type": "plus", "category": "education", "content": "计算机相关专业", "skill": null, "skill_id": null, "weight": 0.5, "quote": "计算机相关专业优先", "char_start": 104, "char_end": 113}, {"id": 3, "req_type": "hard", "category": "skill", "content": "熟悉 HTML", "skill": "HTML", "skill_id": 16, "weight": 1.0, "quote": "熟悉 HTML、CSS 和 JavaScript", "char_start": 118, "char_end": 142}, {"id": 4, "req_type": "hard", "category": "skill", "content": "熟悉 CSS", "skill": "CSS", "skill_id": 17, "weight": 1.0, "quote": "熟悉 HTML、CSS 和 JavaScript", "char_start": 118, "char_end": 142}, {"id": 5, "req_type": "hard", "category": "skill", "content": "熟悉 JavaScript", "skill": "JavaScript", "skill_id": 8, "weight": 1.0, "quote": "熟悉 HTML、CSS 和 JavaScript", "char_start": 118, "char_end": 142}, {"id": 6, "req_type": "hard", "category": "skill", "content": "熟悉 React 或 Vue 其中一种框架", "skill": null, "skill_id": null, "weight": 1.0, "quote": "熟悉 React 或 Vue 其中一种框架", "char_start": 160, "char_end": 181}, {"id": 7, "req_type": "hard", "category": "skill", "content": "理解组件化开发", "skill": "组件化开发", "skill_id": null, "weight": 1.0, "quote": "理解组件化开发", "char_start": 182, "char_end": 189}, {"id": 8, "req_type": "hard", "category": "skill", "content": "了解 TypeScript 并能在项目中使用", "skill": "TypeScript", "skill_id": 9, "weight": 1.0, "quote": "了解 TypeScript，能在项目中使用", "char_start": 194, "char_end": 215}, {"id": 9, "req_type": "hard", "category": "skill", "content": "了解 Vite 或 Webpack 等前端构建工具", "skill": null, "skill_id": null, "weight": 1.0, "quote": "了解 Vite 或 Webpack 等前端构建工具", "char_start": 220, "char_end": 245}, {"id": 10, "req_type": "hard", "category": "skill", "content": "了解 HTTP 协议", "skill": "HTTP", "skill_id": 152, "weight": 1.0, "quote": "了解 HTTP 协议和浏览器的基本工作原理", "char_start": 250, "char_end": 271}, {"id": 11, "req_type": "hard", "category": "skill", "content": "会用 Git 协作开发", "skill": "Git", "skill_id": 103, "weight": 1.0, "quote": "会用 Git 协作开发", "char_start": 276, "char_end": 287}, {"id": 12, "req_type": "plus", "category": "experience", "content": "有移动端适配或微信小程序开发经验", "skill": null, "skill_id": null, "weight": 0.5, "quote": "有移动端适配或微信小程序开发经验", "char_start": 298, "char_end": 314}, {"id": 13, "req_type": "plus", "category": "skill", "content": "用过 ECharts 等可视化库", "skill": "ECharts", "skill_id": 87, "weight": 0.5, "quote": "用过 ECharts 等可视化库", "char_start": 319, "char_end": 335}, {"id": 14, "req_type": "plus", "category": "experience", "content": "有个人作品、技术博客或开源项目", "skill": null, "skill_id": null, "weight": 0.5, "quote": "有个人作品、技术博客或开源项目", "char_start": 340, "char_end": 355}, {"id": 15, "req_type": "soft", "category": "other", "content": "对界面细节和用户体验敏感", "skill": null, "skill_id": null, "weight": 0.3, "quote": "对界面细节和用户体验敏感", "char_start": 365, "char_end": 377}, {"id": 16, "req_type": "soft", "category": "other", "content": "学习能力强", "skill": null, "skill_id": null, "weight": 0.3, "quote": "学习能力强", "char_start": 378, "char_end": 383}, {"id": 17, "req_type": "soft", "category": "other", "content": "善于沟通", "skill": null, "skill_id": null, "weight": 0.3, "quote": "善于沟通", "char_start": 384, "char_end": 388}]';
UPDATE jobs SET domain = 'cs', raw_text = @raw, requirements = @reqs, parse_status = 'success', is_deleted = 0
  WHERE is_template = 1 AND title = '前端开发实习生';
INSERT INTO jobs (user_id, is_template, title, domain, raw_text, requirements, parse_status)
  SELECT NULL, 1, '前端开发实习生', 'cs', @raw, @reqs, 'success' FROM DUAL
  WHERE NOT EXISTS (SELECT 1 FROM jobs WHERE is_template = 1 AND title = '前端开发实习生');

SET @raw = '岗位职责：
1. 参与推荐、分类、预测等业务场景的机器学习模型研发；
2. 负责数据清洗、特征工程、模型训练和效果评估；
3. 跟进相关领域的前沿论文，并尝试在业务中落地。

任职要求：
1. 本科或硕士在读，计算机、人工智能、数学、统计等相关专业；
2. 熟练使用 Python，熟悉 NumPy、Pandas 等数据处理库；
3. 掌握常见的机器学习算法，如逻辑回归、决策树、GBDT、聚类等；
4. 理解深度学习的基本原理，会用 PyTorch 或 TensorFlow 搭建和训练模型；
5. 会用 scikit-learn 完成常规的建模流程；
6. 数学基础扎实，熟悉概率统计和线性代数；
7. 有良好的编程能力和数据结构与算法基础。

加分项：
1. 在 Kaggle 等数据竞赛中取得过较好名次；
2. 以第一作者发表过相关领域的论文；
3. 有推荐系统、自然语言处理或计算机视觉方向的项目经验。

我们希望你：
分析和解决问题的能力强，对数据敏感，能独立推进实验。';
SET @reqs = '[{"id": 1, "req_type": "hard", "category": "education", "content": "本科或硕士在读，计算机、人工智能、数学、统计等相关专业", "skill": null, "skill_id": null, "weight": 1.0, "quote": "本科或硕士在读，计算机、人工智能、数学、统计等相关专业", "char_start": 97, "char_end": 124}, {"id": 2, "req_type": "hard", "category": "skill", "content": "熟练使用 Python", "skill": "Python", "skill_id": 2, "weight": 1.0, "quote": "熟练使用 Python", "char_start": 129, "char_end": 140}, {"id": 3, "req_type": "hard", "category": "skill", "content": "熟悉 NumPy", "skill": "NumPy", "skill_id": 141, "weight": 1.0, "quote": "熟悉 NumPy、Pandas 等数据处理库", "char_start": 141, "char_end": 163}, {"id": 4, "req_type": "hard", "category": "skill", "content": "熟悉 Pandas", "skill": "Pandas", "skill_id": 142, "weight": 1.0, "quote": "熟悉 NumPy、Pandas 等数据处理库", "char_start": 141, "char_end": 163}, {"id": 5, "req_type": "hard", "category": "skill", "content": "掌握常见的机器学习算法", "skill": "机器学习算法", "skill_id": null, "weight": 1.0, "quote": "掌握常见的机器学习算法，如逻辑回归、决策树、GBDT、聚类等", "char_start": 168, "char_end": 198}, {"id": 6, "req_type": "hard", "category": "skill", "content": "理解深度学习的基本原理", "skill": "深度学习", "skill_id": 119, "weight": 1.0, "quote": "理解深度学习的基本原理", "char_start": 203, "char_end": 214}, {"id": 7, "req_type": "hard", "category": "skill", "content": "会用 PyTorch 或 TensorFlow 搭建和训练模型", "skill": null, "skill_id": null, "weight": 1.0, "quote": "会用 PyTorch 或 TensorFlow 搭建和训练模型", "char_start": 215, "char_end": 246}, {"id": 8, "req_type": "hard", "category": "skill", "content": "会用 scikit-learn 完成常规的建模流程", "skill": "scikit-learn", "skill_id": 122, "weight": 1.0, "quote": "会用 scikit-learn 完成常规的建模流程", "char_start": 251, "char_end": 276}, {"id": 9, "req_type": "hard", "category": "skill", "content": "熟悉概率统计", "skill": "概率统计", "skill_id": null, "weight": 1.0, "quote": "数学基础扎实，熟悉概率统计和线性代数", "char_start": 281, "char_end": 299}, {"id": 10, "req_type": "hard", "category": "skill", "content": "熟悉线性代数", "skill": "线性代数", "skill_id": null, "weight": 1.0, "quote": "数学基础扎实，熟悉概率统计和线性代数", "char_start": 281, "char_end": 299}, {"id": 11, "req_type": "hard", "category": "skill", "content": "有良好的编程能力和数据结构与算法基础", "skill": "数据结构与算法", "skill_id": 150, "weight": 1.0, "quote": "有良好的编程能力和数据结构与算法基础", "char_start": 304, "char_end": 322}, {"id": 12, "req_type": "plus", "category": "experience", "content": "在 Kaggle 等数据竞赛中取得过较好名次", "skill": null, "skill_id": null, "weight": 0.5, "quote": "在 Kaggle 等数据竞赛中取得过较好名次", "char_start": 333, "char_end": 355}, {"id": 13, "req_type": "plus", "category": "experience", "content": "以第一作者发表过相关领域的论文", "skill": null, "skill_id": null, "weight": 0.5, "quote": "以第一作者发表过相关领域的论文", "char_start": 360, "char_end": 375}, {"id": 14, "req_type": "plus", "category": "experience", "content": "有推荐系统、自然语言处理或计算机视觉方向的项目经验", "skill": null, "skill_id": null, "weight": 0.5, "quote": "有推荐系统、自然语言处理或计算机视觉方向的项目经验", "char_start": 380, "char_end": 405}, {"id": 15, "req_type": "soft", "category": "other", "content": "分析和解决问题的能力强，对数据敏感，能独立推进实验", "skill": null, "skill_id": null, "weight": 0.3, "quote": "分析和解决问题的能力强，对数据敏感，能独立推进实验", "char_start": 415, "char_end": 440}]';
UPDATE jobs SET domain = 'cs', raw_text = @raw, requirements = @reqs, parse_status = 'success', is_deleted = 0
  WHERE is_template = 1 AND title = '算法实习生（机器学习）';
INSERT INTO jobs (user_id, is_template, title, domain, raw_text, requirements, parse_status)
  SELECT NULL, 1, '算法实习生（机器学习）', 'cs', @raw, @reqs, 'success' FROM DUAL
  WHERE NOT EXISTS (SELECT 1 FROM jobs WHERE is_template = 1 AND title = '算法实习生（机器学习）');

SET @raw = '岗位职责：
1. 参与基于大语言模型的应用开发，如智能问答、知识库助手、Agent 工作流等；
2. 负责 Prompt 设计与调优、检索增强生成（RAG）链路搭建和效果评估；
3. 与后端、产品同学协作，把 AI 能力接入业务系统。

任职要求：
1. 本科及以上学历在读，计算机、人工智能等相关专业；
2. 熟练掌握 Python，有良好的工程编码习惯；
3. 了解大语言模型的基本原理，调用过主流大模型的 API；
4. 熟悉 LangChain 或 LangGraph 等应用开发框架；
5. 理解 RAG 的基本流程，了解文本切分、Embedding 和向量检索；
6. 用过 Milvus、Chroma 等向量数据库其中一种；
7. 能用 FastAPI 或 Flask 编写后端服务。

加分项：
1. 有 Agent 或多智能体应用的开发经验；
2. 了解模型微调，或 vLLM、Ollama 等本地部署方案；
3. 做过完整的大模型应用项目，能说清楚效果是怎么评估的。

我们希望你：
对 AI 技术保持好奇，动手能力强，能快速上手新工具。';
SET @reqs = '[{"id": 1, "req_type": "hard", "category": "education", "content": "本科及以上学历在读，计算机、人工智能等相关专业", "skill": null, "skill_id": null, "weight": 1.0, "quote": "本科及以上学历在读，计算机、人工智能等相关专业", "char_start": 128, "char_end": 151}, {"id": 2, "req_type": "hard", "category": "skill", "content": "熟练掌握 Python", "skill": "Python", "skill_id": 2, "weight": 1.0, "quote": "熟练掌握 Python，有良好的工程编码习惯", "char_start": 156, "char_end": 178}, {"id": 3, "req_type": "hard", "category": "other", "content": "有良好的工程编码习惯", "skill": null, "skill_id": null, "weight": 1.0, "quote": "有良好的工程编码习惯", "char_start": 168, "char_end": 178}, {"id": 4, "req_type": "hard", "category": "skill", "content": "了解大语言模型的基本原理", "skill": "大语言模型", "skill_id": 126, "weight": 1.0, "quote": "了解大语言模型的基本原理，调用过主流大模型的 API", "char_start": 183, "char_end": 209}, {"id": 5, "req_type": "hard", "category": "skill", "content": "熟悉 LangChain 或 LangGraph 等应用开发框架", "skill": null, "skill_id": null, "weight": 1.0, "quote": "熟悉 LangChain 或 LangGraph 等应用开发框架", "char_start": 214, "char_end": 246}, {"id": 6, "req_type": "hard", "category": "skill", "content": "理解 RAG 的基本流程", "skill": "RAG", "skill_id": 127, "weight": 1.0, "quote": "理解 RAG 的基本流程", "char_start": 251, "char_end": 263}, {"id": 7, "req_type": "hard", "category": "skill", "content": "了解文本切分", "skill": "文本切分", "skill_id": null, "weight": 1.0, "quote": "了解文本切分、Embedding 和向量检索", "char_start": 264, "char_end": 286}, {"id": 8, "req_type": "hard", "category": "skill", "content": "了解 Embedding", "skill": "Embedding", "skill_id": 136, "weight": 1.0, "quote": "了解文本切分、Embedding 和向量检索", "char_start": 264, "char_end": 286}, {"id": 9, "req_type": "hard", "category": "skill", "content": "了解向量检索", "skill": "向量检索", "skill_id": null, "weight": 1.0, "quote": "了解文本切分、Embedding 和向量检索", "char_start": 264, "char_end": 286}, {"id": 10, "req_type": "hard", "category": "skill", "content": "用过 Milvus、Chroma 等向量数据库其中一种", "skill": null, "skill_id": null, "weight": 1.0, "quote": "用过 Milvus、Chroma 等向量数据库其中一种", "char_start": 291, "char_end": 318}, {"id": 11, "req_type": "hard", "category": "skill", "content": "能用 FastAPI 或 Flask 编写后端服务", "skill": null, "skill_id": null, "weight": 1.0, "quote": "能用 FastAPI 或 Flask 编写后端服务", "char_start": 323, "char_end": 348}, {"id": 12, "req_type": "plus", "category": "experience", "content": "有 Agent 或多智能体应用的开发经验", "skill": null, "skill_id": null, "weight": 0.5, "quote": "有 Agent 或多智能体应用的开发经验", "char_start": 359, "char_end": 379}, {"id": 13, "req_type": "plus", "category": "skill", "content": "了解模型微调", "skill": "模型微调", "skill_id": 133, "weight": 0.5, "quote": "了解模型微调，或 vLLM、Ollama 等本地部署方案", "char_start": 384, "char_end": 412}, {"id": 14, "req_type": "plus", "category": "skill", "content": "了解 vLLM、Ollama 等本地部署方案", "skill": null, "skill_id": null, "weight": 0.5, "quote": "了解模型微调，或 vLLM、Ollama 等本地部署方案", "char_start": 384, "char_end": 412}, {"id": 15, "req_type": "plus", "category": "experience", "content": "做过完整的大模型应用项目，能说清楚效果是怎么评估的", "skill": null, "skill_id": null, "weight": 0.5, "quote": "做过完整的大模型应用项目，能说清楚效果是怎么评估的", "char_start": 417, "char_end": 442}, {"id": 16, "req_type": "soft", "category": "other", "content": "对 AI 技术保持好奇，动手能力强，能快速上手新工具", "skill": null, "skill_id": null, "weight": 0.3, "quote": "对 AI 技术保持好奇，动手能力强，能快速上手新工具", "char_start": 452, "char_end": 478}]';
UPDATE jobs SET domain = 'cs', raw_text = @raw, requirements = @reqs, parse_status = 'success', is_deleted = 0
  WHERE is_template = 1 AND title = 'AI 应用开发实习生（大模型）';
INSERT INTO jobs (user_id, is_template, title, domain, raw_text, requirements, parse_status)
  SELECT NULL, 1, 'AI 应用开发实习生（大模型）', 'cs', @raw, @reqs, 'success' FROM DUAL
  WHERE NOT EXISTS (SELECT 1 FROM jobs WHERE is_template = 1 AND title = 'AI 应用开发实习生（大模型）');

SET @raw = '岗位职责：
1. 参与产品的功能测试、接口测试和性能测试，编写测试用例并跟踪缺陷；
2. 开发和维护自动化测试脚本与测试工具，提升测试效率；
3. 参与持续集成流程建设，保障版本质量。

任职要求：
1. 本科及以上学历在读，计算机、软件工程等相关专业；
2. 掌握 Python 或 Java 其中一门编程语言；
3. 熟悉软件测试的基本理论和常用的用例设计方法；
4. 会用 pytest 或 JUnit 编写自动化测试；
5. 了解 Selenium 等 UI 自动化工具；
6. 会用 Postman 或 JMeter 做接口测试；
7. 熟悉 Linux 常用命令和基本的 SQL 查询。

加分项：
1. 了解 Jenkins 等 CI/CD 工具；
2. 做过性能测试或自动化测试平台相关的项目；
3. 了解 Docker 的基本使用。

我们希望你：
细心、有耐心，对质量有追求，善于沟通和推动问题解决。';
SET @reqs = '[{"id": 1, "req_type": "hard", "category": "education", "content": "本科及以上学历在读，计算机、软件工程等相关专业", "skill": null, "skill_id": null, "weight": 1.0, "quote": "本科及以上学历在读，计算机、软件工程等相关专业", "char_start": 103, "char_end": 126}, {"id": 2, "req_type": "hard", "category": "skill", "content": "掌握 Python 或 Java 其中一门编程语言", "skill": null, "skill_id": null, "weight": 1.0, "quote": "掌握 Python 或 Java 其中一门编程语言", "char_start": 131, "char_end": 156}, {"id": 3, "req_type": "hard", "category": "skill", "content": "熟悉软件测试的基本理论和常用的用例设计方法", "skill": "软件测试", "skill_id": null, "weight": 1.0, "quote": "熟悉软件测试的基本理论和常用的用例设计方法", "char_start": 161, "char_end": 182}, {"id": 4, "req_type": "hard", "category": "skill", "content": "会用 pytest 或 JUnit 编写自动化测试", "skill": null, "skill_id": null, "weight": 1.0, "quote": "会用 pytest 或 JUnit 编写自动化测试", "char_start": 187, "char_end": 212}, {"id": 5, "req_type": "hard", "category": "skill", "content": "了解 Selenium 等 UI 自动化工具", "skill": "Selenium", "skill_id": 116, "weight": 1.0, "quote": "了解 Selenium 等 UI 自动化工具", "char_start": 217, "char_end": 239}, {"id": 6, "req_type": "hard", "category": "skill", "content": "会用 Postman 或 JMeter 做接口测试", "skill": null, "skill_id": null, "weight": 1.0, "quote": "会用 Postman 或 JMeter 做接口测试", "char_start": 244, "char_end": 269}, {"id": 7, "req_type": "hard", "category": "skill", "content": "熟悉 Linux 常用命令", "skill": "Linux", "skill_id": 106, "weight": 1.0, "quote": "熟悉 Linux 常用命令和基本的 SQL 查询", "char_start": 274, "char_end": 298}, {"id": 8, "req_type": "hard", "category": "skill", "content": "熟悉基本的 SQL 查询", "skill": "SQL", "skill_id": 14, "weight": 1.0, "quote": "熟悉 Linux 常用命令和基本的 SQL 查询", "char_start": 274, "char_end": 298}, {"id": 9, "req_type": "plus", "category": "skill", "content": "了解 Jenkins 等 CI/CD 工具", "skill": "Jenkins", "skill_id": 100, "weight": 0.5, "quote": "了解 Jenkins 等 CI/CD 工具", "char_start": 309, "char_end": 330}, {"id": 10, "req_type": "plus", "category": "experience", "content": "做过性能测试或自动化测试平台相关的项目", "skill": null, "skill_id": null, "weight": 0.5, "quote": "做过性能测试或自动化测试平台相关的项目", "char_start": 335, "char_end": 354}, {"id": 11, "req_type": "plus", "category": "skill", "content": "了解 Docker 的基本使用", "skill": "Docker", "skill_id": 97, "weight": 0.5, "quote": "了解 Docker 的基本使用", "char_start": 359, "char_end": 374}, {"id": 12, "req_type": "soft", "category": "other", "content": "细心、有耐心，对质量有追求，善于沟通和推动问题解决", "skill": null, "skill_id": null, "weight": 0.3, "quote": "细心、有耐心，对质量有追求，善于沟通和推动问题解决", "char_start": 384, "char_end": 409}]';
UPDATE jobs SET domain = 'cs', raw_text = @raw, requirements = @reqs, parse_status = 'success', is_deleted = 0
  WHERE is_template = 1 AND title = '测试开发实习生';
INSERT INTO jobs (user_id, is_template, title, domain, raw_text, requirements, parse_status)
  SELECT NULL, 1, '测试开发实习生', 'cs', @raw, @reqs, 'success' FROM DUAL
  WHERE NOT EXISTS (SELECT 1 FROM jobs WHERE is_template = 1 AND title = '测试开发实习生');

SET @raw = '岗位职责：
1. 负责业务数据的提取、清洗和分析，搭建和维护数据报表；
2. 围绕用户增长、留存、转化等问题做专题分析，输出分析报告和改进建议；
3. 协助搭建指标体系，监控核心指标的异常波动。

任职要求：
1. 本科及以上学历在读，统计学、数学、计算机、经济学等相关专业；
2. 熟练使用 SQL，能独立完成多表关联和数据提取；
3. 熟悉 Python，会用 Pandas 做数据处理和分析；
4. 会用 Matplotlib 或 ECharts 等工具做数据可视化；
5. 掌握基本的统计学知识，了解假设检验和 A/B 测试；
6. 熟练使用 Excel。

加分项：
1. 有数据分析相关的实习经历；
2. 了解 Hive 或 Spark 等大数据工具；
3. 了解常见的机器学习算法。

我们希望你：
逻辑清晰，对数据敏感，能把分析结论讲清楚。';
SET @reqs = '[{"id": 1, "req_type": "hard", "category": "education", "content": "本科及以上学历在读，统计学、数学、计算机、经济学等相关专业", "skill": null, "skill_id": null, "weight": 1.0, "quote": "本科及以上学历在读，统计学、数学、计算机、经济学等相关专业", "char_start": 108, "char_end": 137}, {"id": 2, "req_type": "hard", "category": "skill", "content": "熟练使用 SQL，能独立完成多表关联和数据提取", "skill": "SQL", "skill_id": 14, "weight": 1.0, "quote": "熟练使用 SQL，能独立完成多表关联和数据提取", "char_start": 142, "char_end": 165}, {"id": 3, "req_type": "hard", "category": "skill", "content": "熟悉 Python", "skill": "Python", "skill_id": 2, "weight": 1.0, "quote": "熟悉 Python，会用 Pandas 做数据处理和分析", "char_start": 170, "char_end": 198}, {"id": 4, "req_type": "hard", "category": "skill", "content": "会用 Pandas 做数据处理和分析", "skill": "Pandas", "skill_id": 142, "weight": 1.0, "quote": "熟悉 Python，会用 Pandas 做数据处理和分析", "char_start": 170, "char_end": 198}, {"id": 5, "req_type": "hard", "category": "skill", "content": "会用 Matplotlib 或 ECharts 等工具做数据可视化", "skill": null, "skill_id": null, "weight": 1.0, "quote": "会用 Matplotlib 或 ECharts 等工具做数据可视化", "char_start": 203, "char_end": 236}, {"id": 6, "req_type": "hard", "category": "skill", "content": "掌握基本的统计学知识", "skill": "统计学", "skill_id": null, "weight": 1.0, "quote": "掌握基本的统计学知识，了解假设检验和 A/B 测试", "char_start": 241, "char_end": 266}, {"id": 7, "req_type": "hard", "category": "skill", "content": "了解假设检验", "skill": "假设检验", "skill_id": null, "weight": 1.0, "quote": "掌握基本的统计学知识，了解假设检验和 A/B 测试", "char_start": 241, "char_end": 266}, {"id": 8, "req_type": "hard", "category": "skill", "content": "了解 A/B 测试", "skill": "A/B 测试", "skill_id": 176, "weight": 1.0, "quote": "掌握基本的统计学知识，了解假设检验和 A/B 测试", "char_start": 241, "char_end": 266}, {"id": 9, "req_type": "hard", "category": "skill", "content": "熟练使用 Excel", "skill": "Excel", "skill_id": 156, "weight": 1.0, "quote": "熟练使用 Excel。", "char_start": 271, "char_end": 282}, {"id": 10, "req_type": "plus", "category": "experience", "content": "有数据分析相关的实习经历", "skill": null, "skill_id": null, "weight": 0.5, "quote": "有数据分析相关的实习经历", "char_start": 292, "char_end": 304}, {"id": 11, "req_type": "plus", "category": "skill", "content": "了解 Hive 或 Spark 等大数据工具", "skill": null, "skill_id": null, "weight": 0.5, "quote": "了解 Hive 或 Spark 等大数据工具", "char_start": 309, "char_end": 331}, {"id": 12, "req_type": "plus", "category": "skill", "content": "了解常见的机器学习算法", "skill": "机器学习算法", "skill_id": null, "weight": 0.5, "quote": "了解常见的机器学习算法。", "char_start": 336, "char_end": 348}, {"id": 13, "req_type": "soft", "category": "other", "content": "逻辑清晰，对数据敏感，能把分析结论讲清楚", "skill": null, "skill_id": null, "weight": 0.3, "quote": "逻辑清晰，对数据敏感，能把分析结论讲清楚。", "char_start": 357, "char_end": 378}]';
UPDATE jobs SET domain = 'cs', raw_text = @raw, requirements = @reqs, parse_status = 'success', is_deleted = 0
  WHERE is_template = 1 AND title = '数据分析实习生';
INSERT INTO jobs (user_id, is_template, title, domain, raw_text, requirements, parse_status)
  SELECT NULL, 1, '数据分析实习生', 'cs', @raw, @reqs, 'success' FROM DUAL
  WHERE NOT EXISTS (SELECT 1 FROM jobs WHERE is_template = 1 AND title = '数据分析实习生');

SET @raw = '岗位职责：
1. 负责小红书、抖音、微信公众号等平台账号的内容策划与日常发布；
2. 跟进热点，策划选题，撰写推文和短视频脚本；
3. 统计各平台的内容数据，定期复盘，调整内容方向。

任职要求：
1. 本科及以上学历，新闻传播、广告、中文、市场营销等相关专业优先；
2. 熟悉小红书、抖音、微信公众号等平台的内容规则和推荐机制；
3. 文字功底扎实，能独立撰写推文和短视频脚本；
4. 会用剪映剪辑短视频，会用 Photoshop 或稿定设计做简单配图；
5. 会用 Excel 整理和分析内容数据；
6. 有自媒体账号运营经验者优先；
7. 对热点敏感，执行力强，每周至少到岗 4 天。';
SET @reqs = '[{"id": 1, "req_type": "hard", "category": "education", "content": "本科及以上学历", "skill": null, "skill_id": null, "weight": 1.0, "quote": "本科及以上学历，新闻传播、广告、中文、市场营销等相关专业优先", "char_start": 102, "char_end": 132}, {"id": 2, "req_type": "plus", "category": "education", "content": "新闻传播、广告、中文、市场营销等相关专业优先", "skill": null, "skill_id": null, "weight": 0.5, "quote": "新闻传播、广告、中文、市场营销等相关专业优先", "char_start": 110, "char_end": 132}, {"id": 3, "req_type": "hard", "category": "skill", "content": "熟悉小红书平台的内容规则和推荐机制", "skill": "小红书", "skill_id": 164, "weight": 1.0, "quote": "熟悉小红书、抖音、微信公众号等平台的内容规则和推荐机制", "char_start": 137, "char_end": 164}, {"id": 4, "req_type": "hard", "category": "skill", "content": "熟悉抖音平台的内容规则和推荐机制", "skill": "抖音", "skill_id": 165, "weight": 1.0, "quote": "熟悉小红书、抖音、微信公众号等平台的内容规则和推荐机制", "char_start": 137, "char_end": 164}, {"id": 5, "req_type": "hard", "category": "skill", "content": "熟悉微信公众号平台的内容规则和推荐机制", "skill": "微信公众号", "skill_id": 166, "weight": 1.0, "quote": "熟悉小红书、抖音、微信公众号等平台的内容规则和推荐机制", "char_start": 137, "char_end": 164}, {"id": 6, "req_type": "hard", "category": "skill", "content": "文字功底扎实，能独立撰写推文和短视频脚本", "skill": null, "skill_id": null, "weight": 1.0, "quote": "文字功底扎实，能独立撰写推文和短视频脚本", "char_start": 169, "char_end": 189}, {"id": 7, "req_type": "hard", "category": "skill", "content": "会用剪映剪辑短视频", "skill": "剪映", "skill_id": 160, "weight": 1.0, "quote": "会用剪映剪辑短视频", "char_start": 194, "char_end": 203}, {"id": 8, "req_type": "hard", "category": "skill", "content": "会用 Photoshop 或稿定设计做简单配图", "skill": null, "skill_id": null, "weight": 1.0, "quote": "会用 Photoshop 或稿定设计做简单配图", "char_start": 204, "char_end": 227}, {"id": 9, "req_type": "hard", "category": "skill", "content": "会用 Excel 整理和分析内容数据", "skill": "Excel", "skill_id": 156, "weight": 1.0, "quote": "会用 Excel 整理和分析内容数据", "char_start": 232, "char_end": 250}, {"id": 10, "req_type": "plus", "category": "experience", "content": "有自媒体账号运营经验者优先", "skill": null, "skill_id": null, "weight": 0.5, "quote": "有自媒体账号运营经验者优先", "char_start": 255, "char_end": 268}, {"id": 11, "req_type": "soft", "category": "other", "content": "对热点敏感，执行力强", "skill": null, "skill_id": null, "weight": 0.3, "quote": "对热点敏感，执行力强", "char_start": 273, "char_end": 283}, {"id": 12, "req_type": "hard", "category": "other", "content": "每周至少到岗 4 天", "skill": null, "skill_id": null, "weight": 1.0, "quote": "每周至少到岗 4 天", "char_start": 284, "char_end": 294}]';
UPDATE jobs SET domain = 'ops', raw_text = @raw, requirements = @reqs, parse_status = 'success', is_deleted = 0
  WHERE is_template = 1 AND title = '内容运营实习生（新媒体）';
INSERT INTO jobs (user_id, is_template, title, domain, raw_text, requirements, parse_status)
  SELECT NULL, 1, '内容运营实习生（新媒体）', 'ops', @raw, @reqs, 'success' FROM DUAL
  WHERE NOT EXISTS (SELECT 1 FROM jobs WHERE is_template = 1 AND title = '内容运营实习生（新媒体）');

SET @raw = '岗位职责：
1. 负责用户社群的日常运营和维护，提升用户活跃和留存；
2. 策划并执行拉新、促活类线上活动，跟踪活动数据并复盘；
3. 搭建用户分层和用户画像，配合产品优化用户体验。

任职要求：
1. 本科及以上学历，市场营销、统计学、管理类等相关专业优先；
2. 有社群运营、私域运营或校园活动组织经验；
3. 有独立策划并执行线上活动的经历，能用数据复盘活动效果；
4. 熟练使用 Excel 做数据整理和透视分析，会 SQL 者优先；
5. 了解 AARRR、漏斗分析、留存分析等用户增长的常用方法；
6. 了解 A/B 测试者优先；
7. 沟通能力强，有同理心，执行力强。';
SET @reqs = '[{"id": 1, "req_type": "hard", "category": "education", "content": "本科及以上学历", "skill": null, "skill_id": null, "weight": 1.0, "quote": "本科及以上学历，市场营销、统计学、管理类等相关专业优先", "char_start": 102, "char_end": 129}, {"id": 2, "req_type": "plus", "category": "education", "content": "市场营销、统计学、管理类等相关专业优先", "skill": null, "skill_id": null, "weight": 0.5, "quote": "市场营销、统计学、管理类等相关专业优先", "char_start": 110, "char_end": 129}, {"id": 3, "req_type": "hard", "category": "experience", "content": "有社群运营、私域运营或校园活动组织经验", "skill": null, "skill_id": null, "weight": 1.0, "quote": "有社群运营、私域运营或校园活动组织经验", "char_start": 134, "char_end": 153}, {"id": 4, "req_type": "hard", "category": "experience", "content": "有独立策划并执行线上活动的经历", "skill": null, "skill_id": null, "weight": 1.0, "quote": "有独立策划并执行线上活动的经历", "char_start": 158, "char_end": 173}, {"id": 5, "req_type": "hard", "category": "skill", "content": "能用数据复盘活动效果", "skill": "数据复盘", "skill_id": null, "weight": 1.0, "quote": "能用数据复盘活动效果", "char_start": 174, "char_end": 184}, {"id": 6, "req_type": "hard", "category": "skill", "content": "熟练使用 Excel 做数据整理和透视分析", "skill": "Excel", "skill_id": 156, "weight": 1.0, "quote": "熟练使用 Excel 做数据整理和透视分析", "char_start": 189, "char_end": 210}, {"id": 7, "req_type": "plus", "category": "skill", "content": "会 SQL 者优先", "skill": "SQL", "skill_id": 14, "weight": 0.5, "quote": "会 SQL 者优先", "char_start": 211, "char_end": 220}, {"id": 8, "req_type": "hard", "category": "skill", "content": "了解 AARRR 用户增长方法", "skill": "AARRR", "skill_id": 187, "weight": 1.0, "quote": "了解 AARRR、漏斗分析、留存分析等用户增长的常用方法", "char_start": 225, "char_end": 253}, {"id": 9, "req_type": "hard", "category": "skill", "content": "了解漏斗分析", "skill": "漏斗分析", "skill_id": 185, "weight": 1.0, "quote": "了解 AARRR、漏斗分析、留存分析等用户增长的常用方法", "char_start": 225, "char_end": 253}, {"id": 10, "req_type": "hard", "category": "skill", "content": "了解留存分析", "skill": "留存分析", "skill_id": 186, "weight": 1.0, "quote": "了解 AARRR、漏斗分析、留存分析等用户增长的常用方法", "char_start": 225, "char_end": 253}, {"id": 11, "req_type": "plus", "category": "skill", "content": "了解 A/B 测试者优先", "skill": "A/B 测试", "skill_id": 176, "weight": 0.5, "quote": "了解 A/B 测试者优先", "char_start": 258, "char_end": 270}, {"id": 12, "req_type": "soft", "category": "other", "content": "沟通能力强", "skill": null, "skill_id": null, "weight": 0.3, "quote": "沟通能力强，有同理心，执行力强", "char_start": 275, "char_end": 290}]';
UPDATE jobs SET domain = 'ops', raw_text = @raw, requirements = @reqs, parse_status = 'success', is_deleted = 0
  WHERE is_template = 1 AND title = '用户运营实习生';
INSERT INTO jobs (user_id, is_template, title, domain, raw_text, requirements, parse_status)
  SELECT NULL, 1, '用户运营实习生', 'ops', @raw, @reqs, 'success' FROM DUAL
  WHERE NOT EXISTS (SELECT 1 FROM jobs WHERE is_template = 1 AND title = '用户运营实习生');
