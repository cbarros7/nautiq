FROM flink:1.19.0-scala_2.12-java11

# Instalar Python 3.11 y herramientas de compilación (JDK/gcc) necesarias para arquitectura ARM64
RUN apt-get update -y && \
    apt-get install -y python3 python3-pip python3-dev openjdk-11-jdk gcc g++ && \
    rm -rf /var/lib/apt/lists/*

# Vincular python3 a python por defecto
RUN ln -s /usr/bin/python3 /usr/bin/python || true

# Habilitar plugin nativo de Azure ADLS Gen2 moviéndolo a la carpeta activa de Flink
RUN cp /opt/flink/opt/flink-azure-fs-hadoop-*.jar /opt/flink/lib/

# Descargar conectores y formatos necesarios para Flink 1.19
RUN wget -P /opt/flink/lib/ https://repo.maven.apache.org/maven2/org/apache/flink/flink-sql-connector-kafka/3.2.0-1.19/flink-sql-connector-kafka-3.2.0-1.19.jar && \
    wget -P /opt/flink/lib/ https://repo.maven.apache.org/maven2/org/apache/flink/flink-sql-avro-confluent-registry/1.19.0/flink-sql-avro-confluent-registry-1.19.0.jar && \
    wget -P /opt/flink/lib/ https://repo.maven.apache.org/maven2/org/apache/flink/flink-sql-parquet/1.19.0/flink-sql-parquet-1.19.0.jar && \
    wget -P /opt/flink/lib/ https://repo1.maven.org/maven2/com/getindata/flink-http-connector/0.14.0/flink-http-connector-0.14.0.jar
# Establecer el directorio de trabajo para dependencias de PyFlink
WORKDIR /opt/flink/usrlib
COPY pyproject.toml .

# Descargar Hadoop (Requerido por flink-parquet y azure-fs-hadoop)
RUN wget -q https://archive.apache.org/dist/hadoop/common/hadoop-3.3.4/hadoop-3.3.4.tar.gz && \
    tar -xzf hadoop-3.3.4.tar.gz -C /opt/ && \
    rm hadoop-3.3.4.tar.gz && \
    ln -s /opt/hadoop-3.3.4 /opt/hadoop

# Descargar Kafka CLI tools (Requerido por orchestrator.py para consultar lag)
RUN wget -q https://archive.apache.org/dist/kafka/3.7.0/kafka_2.13-3.7.0.tgz && \
    tar -xzf kafka_2.13-3.7.0.tgz -C /opt/ && \
    rm kafka_2.13-3.7.0.tgz && \
    ln -s /opt/kafka_2.13-3.7.0 /opt/kafka

# Set environment variables — incluir /bin en PATH para Hadoop y Kafka
ENV HADOOP_HOME=/opt/hadoop
ENV PATH="${PATH}:/opt/hadoop/bin:/opt/kafka/bin"
ENV HADOOP_CLASSPATH="/opt/flink/lib/*:/opt/hadoop/etc/hadoop:/opt/hadoop/share/hadoop/common/lib/*:/opt/hadoop/share/hadoop/common/*:/opt/hadoop/share/hadoop/hdfs:/opt/hadoop/share/hadoop/hdfs/lib/*:/opt/hadoop/share/hadoop/hdfs/*:/opt/hadoop/share/hadoop/mapreduce/*:/opt/hadoop/share/hadoop/mapreduce/lib/*:/opt/hadoop/share/hadoop/yarn/*:/opt/hadoop/share/hadoop/yarn/lib/*"

# Instalar PyFlink inyectando dinámicamente JAVA_HOME para compilar la librería pemja (JNI)
RUN JAVA_HOME=$(dirname $(dirname $(readlink -f $(which javac)))) pip3 install --no-cache-dir apache-flink==1.19.0 python-dotenv requests

# Copiar core-site.xml con placeholders (se rellenarán en runtime via entrypoint.sh)
COPY core-site.xml /opt/hadoop/etc/hadoop/core-site.xml

# Copiar y activar entrypoint personalizado que inyecta credenciales Azure en core-site.xml
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
